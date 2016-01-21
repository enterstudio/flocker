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
