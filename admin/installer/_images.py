# Copyright ClusterHQ Inc.  See LICENSE file for details.

"""
Helper utilities for CloudFormation Installer's Packer images.
"""

import json
import sys

from subprocess import check_call

from twisted.python.filepath import FilePath
from twisted.python.usage import Options, UsageError

DEV_ARCHIVE_BUCKET = 'clusterhq-dev-archive'
INSTALLER_IMAGE_BUCKET = 'clusterhq-installer-images'


class NotARelease(Exception):
    """
    Raised if trying to publish documentation to, or packages for a version
    that isn't a release.
    """


class DocumentationRelease(Exception):
    """
    Raised if trying to upload packages for a documentation release.
    """


class PushFailed(Exception):
    """
    Raised if pushing to Git fails.
    """


class PublishInstallerImagesOptions(Options):
    """
    Options for uploading Packer-generated image IDs.
    """
    optParameters = [
        ["target-bucket", None, INSTALLER_IMAGE_BUCKET,
         "The bucket to upload installer AMI names to.\n"],
        ["build-server", None,
         b'http://build.clusterhq.com',
         "The URL of the build-server.\n"],
    ]


def _get_flocker_base_template_json(aws_region):
    """
    """
    input_template_path = FilePath(__file__).parent().descendant(
        ['packer', 'template_ubuntu-14.04_flocker.json'])
    with input_template_path.open('r') as infile:
        base_template = json.load(infile)
    base_template['builders'][0]['ami_regions'] = aws_region
    output_template_path = input_template_path.temporarySibling()
    with output_template_path.open('w') as outfile:
        json.dump(base_template, outfile)
    return output_template_path


class _PackerOutputParser(object):
    """
    Parse the output of ``packer -machine-readable``.
    """
    def __init__(self):
        self.artifacts = []
        self._current_artifact = {}

    def _parse_line_ARTIFACT(self, parts):
        """
        Parse line parts containing information about an artifact.

        :param list parts: The parts of resulting from splitting a comma
            separated packer output line.
        """
        artifact_type = parts[1]
        if parts[4] == 'end':
            self._current_artifact['type'] = artifact_type
            self.artifacts.append(self._current_artifact)
            self._current_artifact = {}
        key = parts[4]
        value = parts[5:]
        if len(value) == 1:
            value = value[0]
        self._current_artifact[key] = value

    def _parse_line(self, line):
        """
        Parse a line of ``packer`` machine readable output.

        :param unicode line: A line to be parsed.
        """
        parts = line.split(",")
        if len(parts) >= 3:
            if parts[2] == 'artifact':
                self._parse_line_ARTIFACT(parts)

    @classmethod
    def parse_string(cls, packer_output):
        """
        Parse a string containing multiple packer machine readable lines.

        :param unicode packer_output: Multiple lines of packer machine readable
            output.
        :returns: A ``_PackerOutputParser`` after parsing the input lines.
        """
        parser = cls()
        for line in packer_output.splitlines():
            parser._parse_line(line)
        return parser


def _unserialize_packer_dict(serialized_packer_dict):
    """
    Parse a packer serialized dictionary.

    :param unicode serialized_packer_dict: The serialized form.
    :return: A ``dict`` of the keys and values found.
    """
    packer_dict = {}
    for item in serialized_packer_dict.split("%!(PACKER_COMMA)"):
        key, value = item.split(":")
        packer_dict[key] = value
    return packer_dict


def _packer_amis(packer_output):
    """
    :return: A ``dict`` of ``{aws_region: ami_id}`` found in the
        ``packer_output``.
    """
    parser = _PackerOutputParser.parse_string(packer_output)
    for artifact in parser.artifacts:
        if artifact['type'] == 'amazon-ebs':
            return _unserialize_packer_dict(artifact["id"])


def publish_installer_images_main(args, base_path, top_level):
    """
    Publish installer images.

    :param list args: The arguments passed to the scripts.
    :param FilePath base_path: The executable being run.
    :param FilePath top_level: The top-level of the flocker repository.
    """
    options = PublishInstallerImagesOptions()

    try:
        options.parseOptions(args)
    except UsageError as e:
        sys.stderr.write("%s: %s\n" % (base_path.basename(), e))
        raise SystemExit(1)
    # template_path = FilePath(__file__).parent().descendant(
    #     ['packer', 'template_ubuntu-14.04_flocker.json'])
    aws_region = 'us-west-1'
    template_path = _get_flocker_base_template_json(aws_region)
    print "TEMPLATE PATH"
    print template_path
    command = ['packer', 'build',
               '-var', "flocker_branch=master",
               '-var', "source_ami=ami-aa1064ca",
               '-machine-readable', template_path.path]
    print ' '.join(command)
    output = check_call(command)

    print "PACKER OUTPUT"
    print output
