# Copyright 2015 ClusterHQ Inc.  See LICENSE file for details.
"""
Provision a new node and add it to an existing cluster.
"""

import sys

from eliot import add_destination, FileDestination

from twisted.internet.defer import Deferred, inlineCallbacks
from twisted.python.usage import UsageError
from twisted.python.filepath import FilePath

from .acceptance import (
    capture_journal,
    capture_upstart,
    eliot_output,
)
from .cluster_setup import (
    RunOptions as SetupOptions,
    make_client,
    wait_for_nodes,
)


class RunOptions(SetupOptions):
    optParameters = [
        ['purpose', None, 'testing',
         "Purpose of the cluster recorded in its metadata where possible."],
        ['control-node', None, None,
         "The address of the cluster's control node."],
        ['cert-directory', None, None,
         "Directory with the cluster certificates. "],
    ]

    def __init__(self, top_level, reactor, ready):
        """
        :param FilePath top_level: The top-level of the Flocker repository.
        :param reactor: The reactor.
        :param Deferred ready: A deferred to fire...
        """
        super(RunOptions, self).__init__(top_level)
        self._reactor = reactor
        self._ready = ready
        # Override default values defined in the base class.
        self['provider'] = self.defaults['provider'] = 'aws'
        self['dataset-backend'] = self.defaults['dataset-backend'] = 'aws'
        self._remove_options(['number-of-nodes=', 'no-keep'])

    def _remove_options(self, to_remove):
        """
        Remove the given options that are defined in the parent classes.

        :param to_remove: The options to rmeove.
        :type to_remove: list of str

        .. note::
            Option names should be given as is,
            parameter names should have '=' suffix.
        """
        self.longOpt = [opt for opt in self.longOpt if opt not in to_remove]

    def postOptions(self):
        if not self['control-node']:
            raise UsageError("Control node address must be provided.")
        if self.get('cert-directory') is None:
            raise UsageError("Certificate directory must be set")

        self.flocker_client = make_client(
            self._reactor,
            self['control-node'],
            FilePath(self['cert-directory']),
        )
        d = self.flocker_client.list_nodes()

        def complete(existing_nodes):
            self['number-of-nodes'] = len(existing_nodes)
            print "Adding a node to the cluster of {} nodes".format(
                self['number-of-nodes']
            )
            # This is run last as it creates the actual "runner" object
            # based on the provided parameters.
            super(RunOptions, self).postOptions()

        d.addCallback(complete)
        d.chainDeferred(self._ready)

    def _check_cert_directory(self):
        cert_path = FilePath(self['cert-directory'])
        self['cert-directory'] = cert_path
        if not cert_path.exists():
            raise UsageError("{} does not exist".format(cert_path.path))
        if not cert_path.isdir():
            raise UsageError("{} is not a directory".format(cert_path.path))


@inlineCallbacks
def main(reactor, args, base_path, top_level):
    """
    :param reactor: Reactor to use.
    :param list args: The arguments passed to the script.
    :param FilePath base_path: The executable being run.
    :param FilePath top_level: The top-level of the Flocker repository.
    """
    add_destination(eliot_output)
    options_ready = Deferred()
    options = RunOptions(top_level=top_level, reactor=reactor,
                         ready=options_ready)
    try:
        options.parseOptions(args)
        yield options_ready
    except UsageError as e:
        sys.stderr.write("%s: %s\n" % (base_path.basename(), e))
        raise SystemExit(1)

    node = None

    def node_cleanup():
        if node is not None:
            try:
                print "Destroying %s" % (node.name,)
                node.destroy()
            except Exception as e:
                print "Failed to destroy %s: %s" % (node.name, e)

    cleanup_id = reactor.addSystemEventTrigger('before', 'shutdown',
                                               node_cleanup)

    from flocker.common.script import eliot_logging_service
    log_writer = eliot_logging_service(
        destination=FileDestination(
            file=open("%s.log" % (base_path.basename(),), "a")
        ),
        reactor=reactor,
        capture_stdout=False)
    log_writer.startService()
    reactor.addSystemEventTrigger(
        'before', 'shutdown', log_writer.stopService)

    control_node = options['control-node']
    if options['distribution'] in ('centos-7',):
        remote_logs_file = open("remote_logs.log", "a")
        capture_journal(reactor, control_node, remote_logs_file)
    elif options['distribution'] in ('ubuntu-14.04', 'ubuntu-15.10'):
        remote_logs_file = open("remote_logs.log", "a")
        capture_upstart(reactor, control_node, remote_logs_file)

    runner = options.runner

    yield runner.ensure_keys(reactor)
    node = runner.create_node()
    yield runner.join_node(reactor, control_node, node)
    yield wait_for_nodes(
        reactor,
        options.flocker_client,
        options['number-of-nodes'] + 1,
    )
    print("Created a new node with address {}".format(node.address))
    if node.private_address is not None:
        print("Private address {}".format(node.private_address))
    reactor.removeSystemEventTrigger(cleanup_id)
