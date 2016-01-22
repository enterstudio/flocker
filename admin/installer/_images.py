# Copyright ClusterHQ Inc.  See LICENSE file for details.

"""
Helper utilities for CloudFormation Installer's Packer images.
"""

import json
import os
from random import randrange
import sys

from subprocess import check_output, check_call

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
        ["region", None, None,
         "A region where the image will be published.\n"],
        ["distribution", None, "ubuntu-14.04",
         "The distribution of operating system to install.\n"],
        ["image_application", None, "flocker",
         "The application which will be installed in the image.\n"],
        ["flocker_branch", None, "master",
         "The branch to install from.\n"],
        ["source_ami", None, "master",
         "The branch to install from.\n"],
    ]


def _packer_template(base_template, aws_region):
    """
    """
    with base_template.open('r') as infile:
        configuration = json.load(infile)
    configuration['builders'][0]['ami_regions'] = aws_region
    output_template_path = base_template.temporarySibling()
    with output_template_path.open('w') as outfile:
        json.dump(configuration, outfile)
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


class RealCommands(object):
    def packer_build(self, flocker_branch, source_ami, template_path):
        command = ['/opt/packer/packer', 'build',
                   '-var', "flocker_branch={}".format(flocker_branch),
                   '-var', "source_ami={}".format(source_ami),
                   '-machine-readable', template_path.path]
        print " ".join(command)
        return check_call(command)


PACKER_TEMPLATE_DIR = FilePath(__file__).sibling('packer')


class _PublishInstallerImagesMain(object):
    def __init__(self, sys_module=None, commands=None):
        if sys_module is None:
            sys_module = sys
        self.sys_module = sys_module

        if commands is None:
            commands = RealCommands()
        self.commands = commands

    def _working_directory(self):
        working_dir_name = 'temp_{}_{}'.format(
            self.base_path.basename(),
            randrange(10 ** 6),
        )
        working_directory = FilePath(os.getcwd()).child(working_dir_name)
        working_directory.makedirs()
        return working_directory

    def _parse_options(self, args):
        options = PublishInstallerImagesOptions()

        try:
            options.parseOptions(args)
        except UsageError as e:
            self.sys_module.stderr.write(
                "Usage Error: %s: %s\n" % (
                    self.base_path.basename(), e
                )
            )
            raise SystemExit(1)
        return options

    def _copy_templates(self, working_directory, base_template):
        packer_configuration_directory = working_directory.child(
            'packer_configuration'
        )
        packer_configuration_directory.makedirs()
        base_template.parent().copyTo(packer_configuration_directory)
        return packer_configuration_directory

    def main(self, args, base_path, top_level):
        """
        Publish installer images.

        :param list args: The arguments passed to the scripts.
        :param FilePath base_path: The executable being run.
        :param FilePath top_level: The top-level of the flocker repository.
        """
        self.base_path = base_path
        self.top_level = top_level

        options = self._parse_options(args)
        template_name = (
            "template_{distribution}_{image_application}.json".format(
                **options
            )
        )
        working_directory = self._working_directory()
        packer_configuration_directory = self._copy_templates(
            base_template=PACKER_TEMPLATE_DIR.child(template_name),
            working_directory=working_directory,
        )
        template_path = _packer_template(
            base_template=packer_configuration_directory.child(template_name),
            aws_region=options["region"]
        )
        output = self.commands.packer_build(
            flocker_branch=options['flocker_branch'],
            source_ami=options['source_ami'],
            template_path=template_path,
        )
        ami_map = _packer_amis(output)
        self.sys_module.stdout.write(json.dumps(ami_map))


publish_installer_images_main = _PublishInstallerImagesMain().main
