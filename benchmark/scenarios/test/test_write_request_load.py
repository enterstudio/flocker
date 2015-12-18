from itertools import repeat
from uuid import uuid4
from ipaddr import IPAddress

from twisted.trial.unittest import SynchronousTestCase
from twisted.internet.defer import Deferred
from twisted.internet.task import Clock
from twisted.python.components import proxyForInterface

from flocker.apiclient._client import (
    IFlockerAPIV1Client, FakeFlockerClient, Node
)

from benchmark.cluster import BenchmarkCluster
from benchmark.scenarios import (
    WriteRequestLoadScenario, WRateMeasurer, WRequestRateTooLow,
    WRequestRateNotReached, WRequestOverload, WDataseCreationTimeout
)
from benchmark.scenarios.read_request_load import DEFAULT_SAMPLE_SIZE

class WRateMeasurerTest(SynchronousTestCase):
    """
    WRateMeasurer tests.
    """

    def send_requests(self, r_measurer, num_req, num_samples):
        """
        Helper function that will send the desired number of request.

        :param r_measurer: `rate_measurer` we are testing.
        :param num_req: number of request we want to send.
        :param num_samples: numbe of samples (interval).
        """
        for i in range(num_samples):
            for i in range(num_req):
                r_measurer.send_request()

    def receive_requests(self, r_measurer, num_req, num_samples):
        """
        Helper function that will receive the desired number of requests.

        :param r_measurer: `rate_measurer` we are testing.
        :param num_req: number of request we want to receive.
        :param num_samples: numbe of samples (interval).
        """
        ignored = ""
        for i in range(num_samples):
            for i in range(num_req):
                r_measurer.receive_request(ignored)
            r_measurer.update_rate()

    def increase_rate(self, r_measurer, num_req, num_samples):
        """
        Helper function that will increase the rate, sending the
        desired number of request, and receiving the same
        amount of them.

        :param r_measurer: `rate_measurer` we are testin.
        :param num_req: number of request we want to make.
        :param num_samples: numbe of samples (interval).
        """
        self.send_requests(r_measurer, num_req, num_samples)
        self.receive_requests(r_measurer, num_req, num_samples)

    def test_rate_is_zero_when_no_samples(self):
        """
        When no samples have been collected, the rate should be 0.
        """
        r = WRateMeasurer()
        self.assertEqual(r.rate(), 0, "Expected initial rate to be zero")

    def test_rate_is_small_when_not_enough_samples(self):
        """
        When the number of samples collected is less than the sample
        size, the rate should be smaller than `req_per_second`.
        """
        r = WRateMeasurer()
        req_per_second = 5

        self.increase_rate(r, req_per_second, (r.sample_size / 2))

        self.assertEqual((req_per_second * (r.sample_size / 2)) /
                         r.sample_size,
                         r.rate())

    def test_rate_is_correct_when_enough_samples(self):
        """
        A WRateMeasurer should correctly report the rate when enough
        samples have been collected.
        """
        r = WRateMeasurer()
        req_per_second = 5

        self.increase_rate(r, req_per_second, r.sample_size)

        self.assertEqual(req_per_second, r.rate())

    def test_old_samples_are_not_considered(self):
        """
        Old samples should be discarded, meaning that only `sample_size`
        number of requests are considered for the rate, and when receiving
        a new sample, the oldest one is discarded.
        """
        r = WRateMeasurer()
        req_per_second = 5
        # generate samples that should get lost
        self.increase_rate(r, 100, r.sample_size/2)

        # generate r.sample_size samples that will make the initial
        # ones not count
        self.increase_rate(r, req_per_second, r.sample_size)

        self.assertEqual(req_per_second, r.rate())

    def test_only_received_samples_considered_in_rate(self):
        """
        The rate should be based on the number of received requests,
        not the number of sent requests.
        """
        r = WRateMeasurer()
        send_per_second = 100
        rec_per_second = 5

        self.send_requests(r, send_per_second, r.sample_size)
        self.receive_requests(r, rec_per_second, r.sample_size)

        self.assertEqual(rec_per_second, r.rate())


class RequestDroppingFakeFlockerClient(
    proxyForInterface(IFlockerAPIV1Client)
):
    """
    A FakeFlockerClient that can drop alternating requests.
    """
    def __init__(self, nodes):
        super(RequestDroppingFakeFlockerClient, self).__init__(nodes)
        self.drop_requests = False
        self._dropped_last_request = False
        self._real_nodes = nodes

    def move_dataset(self, primary, dataset_id, configuration_tag=None):
        if not self.drop_requests:
            return super(RequestDroppingFakeFlockerClient, self).list_nodes()
        else:
            if self._dropped_last_request:
                self._dropped_last_request = False
                return super(RequestDroppingFakeFlockerClient,
                             self).list_nodes()
            self._dropped_last_request = True
        return Deferred()

class UnresponsiveDatasetCreationFakeFlockerClient(
    proxyForInterface(IFlockerAPIV1Client)
):
    """
    A FakeFlockerClient that can drop alternating requests.
    """
    def __init__(self, nodes):
        super(UnresponsiveDatasetCreationFakeFlockerClient, self).__init__(nodes)
        self.drop_requests = False
        self._dropped_last_request = False
        self._real_nodes = nodes

    def create_dataset(self, primary, maximum_size=None, dataset_id=None,
                       metadata=None, configuration_tag=None):
        return Deferred()



class WriteRequestLoadScenarioTest(SynchronousTestCase):
    """
    WriteRequestLoadScenario tests.
    """
    def setUp(self):
        self.node1 = Node(uuid=uuid4(), public_address=IPAddress('10.0.0.1'))
        self.node2 = Node(uuid=uuid4(), public_address=IPAddress('10.0.0.2'))

    def make_cluster(self, FlockerClientInstance):
        """
        Create a cluster that can be used by the scenario tests.
        """
        return BenchmarkCluster(
            self.node1.public_address,
            lambda reactor: FlockerClientInstance,
            {self.node1.public_address, self.node2.public_address},
        )

    def get_fake_flocker_client_instance(self):
        """
        Returns a `FakeFlockerClient` instance with the nodes
        defined in the init.
        """
        return FakeFlockerClient([self.node1, self.node2])

    def get_dropping_flocker_client_instance(self):
        """
        Returns a `FakeFlockerClient` instance with the nodes
        defined in the init.
        """
        return RequestDroppingFakeFlockerClient(
            self.get_fake_flocker_client_instance())

    def get_unresponsive_flocker_client_instance(self):
        """
        Returns a `RequestDroppingFakeFlockerClient` instance
        unsing the nodes defined in the init.
        """
        return UnresponsiveDatasetCreationFakeFlockerClient(
            self.get_fake_flocker_client_instance())

    def test_setup_generates_dataset(self):
        """
        `WriteRequestLoadScenario` starts and stops without collapsing.
        """
        c = Clock()
        cluster = self.make_cluster(self.get_fake_flocker_client_instance())
        s = WriteRequestLoadScenario(c, cluster, 5, interval=3)

        def assert_created(returned_datasets):
            self.assertNotEqual(returned_datasets, [])

        # Create a datasest and verify we get a success
        d = s._create_dataset(self.node1)
        self.successResultOf(d)

        # Verify that a dataset is actually being created
        d2 = s.control_service.list_datasets_configuration()
        d2.addCallback(assert_created)
        s.stop()

    def test_setup_retries_generating_dataset(self):
        # Not implemented. This will just return an error
        # Should we implement it?
        pass

    def test_setup_timeout_when_datasat_not_created(self):
        """
        `WriteRequestLoadScenario` should timeout if the setup the dataset
        creation does not complete within the given time.
        """
        c = Clock()
        cluster = self.make_cluster(
            self.get_unresponsive_flocker_client_instance())
        s = WriteRequestLoadScenario(c, cluster, 5, interval=3)

        d = s.start()
        c.pump(repeat(1, s.timeout+1))

        failure = self.failureResultOf(d)
        self.assertIsInstance(failure.value, WDataseCreationTimeout)

    def test_write_request_load_succeeds(self):
        """
        WriteRequestLoadScenario starts and stops without collapsing.
        """
        c = Clock()
        cluster = self.make_cluster(self.get_fake_flocker_client_instance())
        s = WriteRequestLoadScenario(c, cluster, 5, interval=3)

        d = s.start()

        # Request rate samples are taken at most every second and by
        # default, 5 samples are required to establish the rate.
        # The sample recorded at nth second is the sample for the
        # (n - 1)th second, therefore we need to advance the clock by
        # n + 1 seconds to obtain a rate for n samples.
        c.pump(repeat(1, DEFAULT_SAMPLE_SIZE + 1))
        s.maintained().addBoth(lambda x: self.fail())
        d.addCallback(lambda ignored: s.stop())
        self.successResultOf(d)

    def test_scenario_throws_exception_when_rate_drops(self):
        """
        WriteRequestLoadScenario raises RequestRateTooLow if rate
        drops below the requested rate.

        Establish the requested rate by having the FakeFlockerClient
        respond to all requests, then lower the rate by dropping
        alternate requeeas. This should result in RequestRateTooLow
        being raised.
        """
        c = Clock()
        cluster = self.make_cluster(
            self.get_dropping_flocker_client_instance())
        s = WriteRequestLoadScenario(c, cluster, 5, interval=1)

        s.start()

        # Advance the clock by DEFAULT_SAMPLE_SIZE + 1 seconds to
        # establish the requested rate.
        c.pump(repeat(1, DEFAULT_SAMPLE_SIZE + 1))
        cluster.get_control_service(c).drop_requests = True

        # Advance the clock by 3 seconds so that a request is dropped
        # and a new rate which is below the target can be established.
        c.pump(repeat(1, 3))

        failure = self.failureResultOf(s.maintained())
        self.assertIsInstance(failure.value, WRequestRateTooLow)

    def test_scenario_throws_exception_if_requested_rate_not_reached(self):
        """
        WriteRequestLoadScenario raises RequestRateNotReached if the
        target rate cannot be established within a given timeframe.
        """
        c = Clock()
        cluster = self.make_cluster(
            self.get_dropping_flocker_client_instance())
        s = WriteRequestLoadScenario(c, cluster, 5, interval=1)
        cluster.get_control_service(c).drop_requests = True
        d = s.start()

        # Continue the clock for one second longer than the timeout
        # value to allow the timeout to be triggered.
        c.pump(repeat(1, s.timeout + 15))

        failure = self.failureResultOf(d)
        self.assertIsInstance(failure.value, WRequestRateNotReached)

    def test_scenario_throws_exceptions_if_overloads(self):
        """
        `WriteRequestLoadScenarioTest` raises `RequestOverload` if,
        once we start monitoring the scenario, we go over the max
        tolerated difference between sent requests and received requests.

        Note that, right now, the only way to make it fail is to generate
        this different before we start monitoring the scenario.
        Once we implement some kind of tolerance, to allow small highs/ups
        on the rates, we can update this tests to trigger the exception
        in a more realistic manner.
        """
        # XXX update this tests when we add tolerance to the rate going
        # a bit up and down.
        c = Clock()
        cluster = self.make_cluster(self.get_dropping_flocker_client_instance())
        req_per_second = 2
        sample_size = 20
        s = WriteRequestLoadScenario(c, cluster, req_per_second,
                                     interval=sample_size)
        dropped_req_per_sec = req_per_second / 2
        seconds_to_overload = s.max_outstanding / dropped_req_per_sec

        s.start()
        # Reach initial rate
        cluster.get_control_service(c).drop_requests = True
        # Initially, we generate enough dropped request to make it crash once
        # we start monitoring the scenario
        c.pump(repeat(1, seconds_to_overload+1))
        # We stop dropping requests
        cluster.get_control_service(c).drop_requests = False
        # Now we generate the initial rate to start monitoring the scenario
        c.pump(repeat(1, sample_size+1))
        # We only need to advance one more second (first loop in the monitoring
        # loop) to make it crash with RequestOverload
        c.pump(repeat(1, 1))

        failure = self.failureResultOf(s.maintained())
        self.assertIsInstance(failure.value, WRequestOverload)
