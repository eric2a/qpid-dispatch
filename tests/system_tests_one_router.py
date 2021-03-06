#
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
#

import unittest
from proton import Message, Delivery, PENDING, ACCEPTED, REJECTED
from system_test import TestCase, Qdrouterd, main_module
from proton.handlers import MessagingHandler
from proton.reactor import Container, AtMostOnce, AtLeastOnce
from proton.utils import BlockingConnection, SyncRequestResponse
from qpid_dispatch.management.client import Node

CONNECTION_PROPERTIES = {u'connection': u'properties', u'int_property': 6451}

class RouterTest(TestCase):
    """System tests involving a single router"""
    @classmethod
    def setUpClass(cls):
        """Start a router and a messenger"""
        super(RouterTest, cls).setUpClass()
        name = "test-router"
        config = Qdrouterd.Config([
            ('router', {'mode': 'standalone', 'id': 'QDR'}),

            # Setting the stripAnnotations to 'no' so that the existing tests will work.
            # Setting stripAnnotations to no will not strip the annotations and any tests that were already in this file
            # that were expecting the annotations to not be stripped will continue working.
            ('listener', {'port': cls.tester.get_port(), 'maxFrameSize': '2048', 'stripAnnotations': 'no'}),

            # The following listeners were exclusively added to test the stripAnnotations attribute in qdrouterd.conf file
            # Different listeners will be used to test all allowed values of stripAnnotations ('no', 'both', 'out', 'in')
            ('listener', {'port': cls.tester.get_port(), 'maxFrameSize': '2048', 'stripAnnotations': 'no'}),
            ('listener', {'port': cls.tester.get_port(), 'maxFrameSize': '2048', 'stripAnnotations': 'both'}),
            ('listener', {'port': cls.tester.get_port(), 'maxFrameSize': '2048', 'stripAnnotations': 'out'}),
            ('listener', {'port': cls.tester.get_port(), 'maxFrameSize': '2048', 'stripAnnotations': 'in'}),

            ('address', {'prefix': 'closest', 'distribution': 'closest'}),
            ('address', {'prefix': 'spread', 'distribution': 'balanced'}),
            ('address', {'prefix': 'multicast', 'distribution': 'multicast'}),
        ])
        cls.router = cls.tester.qdrouterd(name, config)
        cls.router.wait_ready()
        cls.address = cls.router.addresses[0]

    def test_01_pre_settled(self):
        addr = self.address+"/pre_settled/1"
        M1 = self.messenger()
        M2 = self.messenger()

        M1.start()
        M2.start()
        M2.subscribe(addr)

        tm = Message()
        rm = Message()

        tm.address = addr
        for i in range(100):
            tm.body = {'number': i}
            M1.put(tm)
        M1.send()

        for i in range(100):
            M2.recv(1)
            M2.get(rm)
            self.assertEqual(i, rm.body['number'])

        M1.stop()
        M2.stop()

    def test_02a_multicast_unsettled(self):
        addr = self.address+"/multicast.unsettled.1"
        M1 = self.messenger()
        M2 = self.messenger()
        M3 = self.messenger()
        M4 = self.messenger()


        M1.outgoing_window = 5
        M2.incoming_window = 5
        M3.incoming_window = 5
        M4.incoming_window = 5

        M1.start()
        M2.start()
        M3.start()
        M4.start()

        M2.subscribe(addr)
        M3.subscribe(addr)
        M4.subscribe(addr)

        tm = Message()
        rm = Message()

        tm.address = addr
        for i in range(2):
            tm.body = {'number': i}
            M1.put(tm)
        M1.send(0)

        for i in range(2):
            M2.recv(1)
            trk = M2.get(rm)
            M2.accept(trk)
            M2.settle(trk)
            self.assertEqual(i, rm.body['number'])

            M3.recv(1)
            trk = M3.get(rm)
            M3.accept(trk)
            M3.settle(trk)
            self.assertEqual(i, rm.body['number'])

            M4.recv(1)
            trk = M4.get(rm)
            M4.accept(trk)
            M4.settle(trk)
            self.assertEqual(i, rm.body['number'])

        M1.stop()
        M2.stop()
        M3.stop()
        M4.stop()


    def test_02b_disp_to_closed_connection(self):
        addr = self.address+"/pre_settled/2"
        M1 = self.messenger()
        M2 = self.messenger()


        M1.outgoing_window = 5
        M2.incoming_window = 5

        M1.start()
        M2.start()
        M2.subscribe(addr)

        tm = Message()
        rm = Message()

        tm.address = addr
        for i in range(2):
            tm.body = {'number': i}
            M1.put(tm)
        M1.send(0)
        M1.stop()

        for i in range(2):
            M2.recv(1)
            trk = M2.get(rm)
            M2.accept(trk)
            M2.settle(trk)
            self.assertEqual(i, rm.body['number'])

        M2.stop()


    def test_02c_sender_settles_first(self):
        addr = self.address+"/settled/senderfirst/1"
        M1 = self.messenger()
        M2 = self.messenger()


        M1.outgoing_window = 5
        M2.incoming_window = 5

        M1.start()
        M2.start()
        M2.subscribe(addr)

        tm = Message()
        rm = Message()

        tm.address = addr
        tm.body = {'number': 0}
        ttrk = M1.put(tm)
        M1.send(0)

        M1.settle(ttrk)
        M1.flush()
        M2.flush()

        M2.recv(1)
        rtrk = M2.get(rm)
        M2.accept(rtrk)
        M2.settle(rtrk)
        self.assertEqual(0, rm.body['number'])

        M1.flush()
        M2.flush()

        M1.stop()
        M2.stop()


    def test_03_propagated_disposition(self):
        addr = self.address+"/unsettled/1"
        M1 = self.messenger()
        M2 = self.messenger()

        M1.outgoing_window = 5
        M2.incoming_window = 5

        M1.start()
        M2.start()
        M2.subscribe(addr)

        tm = Message()
        rm = Message()

        tm.address = addr
        tm.body = {'number': 0}

        ##
        ## Test ACCEPT
        ##
        tx_tracker = M1.put(tm)
        M1.send(0)
        M2.recv(1)
        rx_tracker = M2.get(rm)
        self.assertEqual(0, rm.body['number'])
        self.assertEqual(PENDING, M1.status(tx_tracker))

        M2.accept(rx_tracker)
        M2.settle(rx_tracker)

        M2.flush()
        M1.flush()

        self.assertEqual(ACCEPTED, M1.status(tx_tracker))

        ##
        ## Test REJECT
        ##
        tx_tracker = M1.put(tm)
        M1.send(0)
        M2.recv(1)
        rx_tracker = M2.get(rm)
        self.assertEqual(0, rm.body['number'])
        self.assertEqual(PENDING, M1.status(tx_tracker))

        M2.reject(rx_tracker)
        M2.settle(rx_tracker)

        M2.flush()
        M1.flush()

        self.assertEqual(REJECTED, M1.status(tx_tracker))

        M1.stop()
        M2.stop()


    def test_04_unsettled_undeliverable(self):
        addr = self.address+"/unsettled_undeliverable/1"
        M1 = self.messenger()

        M1.outgoing_window = 5

        M1.start()
        M1.timeout = 1
        tm = Message()
        tm.address = addr
        tm.body = {'number': 200}

        exception = False
        try:
            M1.put(tm)
            M1.send(0)
            M1.flush()
        except Exception:
            exception = True

        self.assertEqual(exception, True)

        M1.stop()


    def test_05_three_ack(self):
        addr = self.address+"/three_ack/1"
        M1 = self.messenger()
        M2 = self.messenger()

        M1.outgoing_window = 5
        M2.incoming_window = 5

        M1.start()
        M2.start()
        M2.subscribe(addr)

        tm = Message()
        rm = Message()

        tm.address = addr
        tm.body = {'number': 200}

        tx_tracker = M1.put(tm)
        M1.send(0)
        M2.recv(1)
        rx_tracker = M2.get(rm)
        self.assertEqual(200, rm.body['number'])
        self.assertEqual(PENDING, M1.status(tx_tracker))

        M2.accept(rx_tracker)

        M2.flush()
        M1.flush()

        self.assertEqual(ACCEPTED, M1.status(tx_tracker))

        M1.settle(tx_tracker)

        M1.flush()
        M2.flush()

        ##
        ## We need a way to verify on M2 (receiver) that the tracker has been
        ## settled on the M1 (sender).  [ See PROTON-395 ]
        ##

        M2.settle(rx_tracker)

        M2.flush()
        M1.flush()

        M1.stop()
        M2.stop()


#    def test_06_link_route_sender(self):
#        pass

#    def test_07_link_route_receiver(self):
#        pass


    def test_08_message_annotations(self):
        addr = self.address+"/ma/1"
        M1 = self.messenger()
        M2 = self.messenger()


        M1.start()
        M2.start()
        M2.subscribe(addr)

        tm = Message()
        rm = Message()

        tm.address = addr


        ##
        ## No inbound delivery annotations
        ##
        for i in range(10):
            tm.body = {'number': i}
            M1.put(tm)
        M1.send()

        for i in range(10):
            M2.recv(1)
            M2.get(rm)
            self.assertEqual(i, rm.body['number'])
            ma = rm.annotations
            self.assertEqual(ma.__class__, dict)
            self.assertEqual(ma['x-opt-qd.ingress'], '0/QDR')
            self.assertEqual(ma['x-opt-qd.trace'], ['0/QDR'])

        ##
        ## Pre-existing ingress
        ##
        tm.annotations = {'x-opt-qd.ingress': 'ingress-router'}
        for i in range(10):
            tm.body = {'number': i}
            M1.put(tm)
        M1.send()

        for i in range(10):
            M2.recv(1)
            M2.get(rm)
            self.assertEqual(i, rm.body['number'])
            ma = rm.annotations
            self.assertEqual(ma.__class__, dict)
            self.assertEqual(ma['x-opt-qd.ingress'], 'ingress-router')
            self.assertEqual(ma['x-opt-qd.trace'], ['0/QDR'])

        ##
        ## Invalid trace type
        ##
        tm.annotations = {'x-opt-qd.trace' : 45}
        for i in range(10):
            tm.body = {'number': i}
            M1.put(tm)
        M1.send()

        for i in range(10):
            M2.recv(1)
            M2.get(rm)
            self.assertEqual(i, rm.body['number'])
            ma = rm.annotations
            self.assertEqual(ma.__class__, dict)
            self.assertEqual(ma['x-opt-qd.ingress'], '0/QDR')
            self.assertEqual(ma['x-opt-qd.trace'], ['0/QDR'])

        ##
        ## Empty trace
        ##
        tm.annotations = {'x-opt-qd.trace' : []}
        for i in range(10):
            tm.body = {'number': i}
            M1.put(tm)
        M1.send()

        for i in range(10):
            M2.recv(1)
            M2.get(rm)
            self.assertEqual(i, rm.body['number'])
            ma = rm.annotations
            self.assertEqual(ma.__class__, dict)
            self.assertEqual(ma['x-opt-qd.ingress'], '0/QDR')
            self.assertEqual(ma['x-opt-qd.trace'], ['0/QDR'])

        ##
        ## Non-empty trace
        ##
        tm.annotations = {'x-opt-qd.trace' : ['0/first.hop']}
        for i in range(10):
            tm.body = {'number': i}
            M1.put(tm)
        M1.send()

        for i in range(10):
            M2.recv(1)
            M2.get(rm)
            self.assertEqual(i, rm.body['number'])
            ma = rm.annotations
            self.assertEqual(ma.__class__, dict)
            self.assertEqual(ma['x-opt-qd.ingress'], '0/QDR')
            self.assertEqual(ma['x-opt-qd.trace'], ['0/first.hop', '0/QDR'])

        M1.stop()
        M2.stop()

    # Tests stripping of ingress and egress annotations.
    # There is a property in qdrouter.json called stripAnnotations with possible values of ["in", "out", "both", "no"]
    # The default for stripAnnotations is "both" (which means strip annotations on both ingress and egress)
    # This test will test the stripAnnotations = no option - meaning no annotations must be stripped.
    # We will send in a custom annotation and make that we get back 3 annotations on the received message
    # Skipping this test temporarily
    def notest_08a_test_strip_message_annotations_no_custom_not_implemented(self):
        addr = self.router.addresses[1]+"/strip_message_annotations_no_custom/1"

        M1 = self.messenger()
        M2 = self.messenger()

        M1.start()
        M2.start()
        M2.subscribe(addr)

        ingress_message = Message()
        ingress_message.address = addr
        ingress_message.body = {'message': 'Hello World!'}
        ingress_message_annotations = {}
        ingress_message_annotations['custom-annotation'] = '1/Custom_Annotation'


        ingress_message.annotations = ingress_message_annotations

        M1.put(ingress_message)
        M1.send()

        # Receive the message
        M2.recv(1)
        egress_message = Message()
        M2.get(egress_message)

        #Make sure 'Hello World!' is in the message body dict
        self.assertEqual('Hello World!', egress_message.body['message'])


        egress_message_annotations = egress_message.annotations

        self.assertEqual(egress_message_annotations.__class__, dict)
        self.assertEqual(egress_message_annotations['custom-annotation'], '1/Custom_Annotation')
        self.assertEqual(egress_message_annotations['x-opt-qd.ingress'], '0/QDR')
        self.assertEqual(egress_message_annotations['x-opt-qd.trace'], ['0/QDR'])

        M1.stop()
        M2.stop()

    #stripAnnotations property is set to "no"
    def test_08a_test_strip_message_annotations_no(self):
        addr = self.router.addresses[1]+"/strip_message_annotations_no/1"

        M1 = self.messenger()
        M2 = self.messenger()

        M1.start()
        M2.start()
        M2.subscribe(addr)

        ingress_message = Message()
        ingress_message.address = addr
        ingress_message.body = {'message': 'Hello World!'}
        ingress_message_annotations = {}

        ingress_message.annotations = ingress_message_annotations

        M1.put(ingress_message)
        M1.send()

        # Receive the message
        M2.recv(1)
        egress_message = Message()
        M2.get(egress_message)

        #Make sure 'Hello World!' is in the message body dict
        self.assertEqual('Hello World!', egress_message.body['message'])


        egress_message_annotations = egress_message.annotations

        self.assertEqual(egress_message_annotations.__class__, dict)
        self.assertEqual(egress_message_annotations['x-opt-qd.ingress'], '0/QDR')
        self.assertEqual(egress_message_annotations['x-opt-qd.trace'], ['0/QDR'])

        M1.stop()
        M2.stop()

    #stripAnnotations property is set to "no"
    def test_08a_test_strip_message_annotations_no_add_trace(self):
        addr = self.router.addresses[1]+"/strip_message_annotations_no_add_trace/1"

        M1 = self.messenger()
        M2 = self.messenger()

        M1.start()
        M2.start()
        M2.subscribe(addr)

        ingress_message = Message()
        ingress_message.address = addr
        ingress_message.body = {'message': 'Hello World!'}

        ##
        ## Pre-existing ingress and trace
        ##
        ingress_message_annotations = {'x-opt-qd.ingress': 'ingress-router', 'x-opt-qd.trace': ['0/QDR.1']}
        ingress_message.annotations = ingress_message_annotations

        ingress_message.annotations = ingress_message_annotations

        M1.put(ingress_message)
        M1.send()

        # Receive the message
        M2.recv(1)
        egress_message = Message()
        M2.get(egress_message)

        #Make sure 'Hello World!' is in the message body dict
        self.assertEqual('Hello World!', egress_message.body['message'])


        egress_message_annotations = egress_message.annotations

        self.assertEqual(egress_message_annotations.__class__, dict)
        self.assertEqual(egress_message_annotations['x-opt-qd.ingress'], 'ingress-router')
        self.assertEqual(egress_message_annotations['x-opt-qd.trace'], ['0/QDR.1', '0/QDR'])

        M1.stop()
        M2.stop()


    #Dont send any pre-existing ingress or trace annotations. Make sure that there are no outgoing message annotations
    #stripAnnotations property is set to "both"
    def test_08a_test_strip_message_annotations_both(self):
        addr = self.router.addresses[2]+"/strip_message_annotations_both/1"

        M1 = self.messenger()
        M2 = self.messenger()

        M1.start()
        M2.start()
        M2.subscribe(addr)

        ingress_message = Message()
        ingress_message.address = addr
        ingress_message.body = {'message': 'Hello World!'}

        #Put and send the message
        M1.put(ingress_message)
        M1.send()

        # Receive the message
        M2.recv(1)
        egress_message = Message()
        M2.get(egress_message)

        self.assertEqual(egress_message.annotations, None)

        M1.stop()
        M2.stop()

    #Dont send any pre-existing ingress or trace annotations. Make sure that there are no outgoing message annotations
    #stripAnnotations property is set to "out"
    def test_08a_test_strip_message_annotations_out(self):
        addr = self.router.addresses[3]+"/strip_message_annotations_out/1"

        M1 = self.messenger()
        M2 = self.messenger()

        M1.start()
        M2.start()
        M2.subscribe(addr)

        ingress_message = Message()
        ingress_message.address = addr
        ingress_message.body = {'message': 'Hello World!'}

        #Put and send the message
        M1.put(ingress_message)
        M1.send()

        # Receive the message
        M2.recv(1)
        egress_message = Message()
        M2.get(egress_message)

        self.assertEqual(egress_message.annotations, None)

        M1.stop()
        M2.stop()

    #Send in pre-existing trace and ingress and annotations and make sure that they are not in the outgoing annotations.
    #stripAnnotations property is set to "in"
    def test_08a_test_strip_message_annotations_in(self):
        addr = self.router.addresses[4]+"/strip_message_annotations_in/1"

        M1 = self.messenger()
        M2 = self.messenger()

        M1.start()
        M2.start()
        M2.subscribe(addr)

        ingress_message = Message()
        ingress_message.address = addr
        ingress_message.body = {'message': 'Hello World!'}

        ##
        ## Pre-existing ingress and trace
        ##
        ingress_message_annotations = {'x-opt-qd.ingress': 'ingress-router', 'x-opt-qd.trace': ['0/QDR.1']}
        ingress_message.annotations = ingress_message_annotations

        #Put and send the message
        M1.put(ingress_message)
        M1.send()

        # Receive the message
        M2.recv(1)
        egress_message = Message()
        M2.get(egress_message)

         #Make sure 'Hello World!' is in the message body dict
        self.assertEqual('Hello World!', egress_message.body['message'])

        egress_message_annotations = egress_message.annotations

        self.assertEqual(egress_message_annotations.__class__, dict)
        self.assertEqual(egress_message_annotations['x-opt-qd.ingress'], '0/QDR')
        self.assertEqual(egress_message_annotations['x-opt-qd.trace'], ['0/QDR'])

        M1.stop()
        M2.stop()


    def test_09_management(self):
        addr  = "amqp:/$management"

        M = self.messenger()
        M.start()
        M.route("amqp:/*", self.address+"/$1")
        sub = M.subscribe("amqp:/#")
        reply = sub.address

        request  = Message()
        response = Message()

        request.address        = addr
        request.reply_to       = reply
        request.correlation_id = "C1"
        request.properties     = {u'type':u'org.amqp.management', u'name':u'self', u'operation':u'GET-MGMT-NODES'}

        M.put(request)
        M.send()
        M.recv()
        M.get(response)

        assert response.properties['statusCode'] == 200, response.properties['statusCode']
        self.assertEqual(response.correlation_id, "C1")
        self.assertEqual(response.body, [])

        request.address        = addr
        request.reply_to       = reply
        request.correlation_id = 135
        request.properties     = {u'type':u'org.amqp.management', u'name':u'self', u'operation':u'GET-MGMT-NODES'}

        M.put(request)
        M.send()
        M.recv()
        M.get(response)

        self.assertEqual(response.properties['statusCode'], 200)
        self.assertEqual(response.correlation_id, 135)
        self.assertEqual(response.body, [])

        request.address        = addr
        request.reply_to       = reply
        request.properties     = {u'type':u'org.amqp.management', u'name':u'self', u'operation':u'GET-MGMT-NODES'}

        M.put(request)
        M.send()
        M.recv()
        M.get(response)

        self.assertEqual(response.properties['statusCode'], 200)
        self.assertEqual(response.body, [])

        M.stop()


    def test_09a_management_no_reply(self):
        addr  = "amqp:/$management"

        M = self.messenger()
        M.start()
        M.route("amqp:/*", self.address+"/$1")

        request  = Message()

        request.address        = addr
        request.correlation_id = "C1"
        request.properties     = {u'type':u'org.amqp.management', u'name':u'self', u'operation':u'GET-MGMT-NODES'}

        M.put(request)
        M.send()

        M.put(request)
        M.send()

        M.stop()


    def test_09c_management_get_operations(self):
        addr  = "amqp:/_local/$management"

        M = self.messenger()
        M.start()
        M.route("amqp:/*", self.address+"/$1")
        sub = M.subscribe("amqp:/#")
        reply = sub.address

        request  = Message()
        response = Message()

        ##
        ## Unrestricted request
        ##
        request.address    = addr
        request.reply_to   = reply
        request.properties = {u'type':u'org.amqp.management', u'name':u'self', u'operation':u'GET-OPERATIONS'}

        M.put(request)
        M.send()
        M.recv()
        M.get(response)

        self.assertEqual(response.properties['statusCode'], 200)
        self.assertEqual(response.body.__class__, dict)
        self.assertTrue('org.apache.qpid.dispatch.router' in response.body.keys())
        self.assertTrue(len(response.body.keys()) > 2)
        self.assertTrue(response.body['org.apache.qpid.dispatch.router'].__class__, list)

        M.stop()


    def test_09d_management_not_implemented(self):
        addr  = "amqp:/$management"

        M = self.messenger()
        M.start()
        M.route("amqp:/*", self.address+"/$1")
        sub = M.subscribe("amqp:/#")
        reply = sub.address

        request  = Message()
        response = Message()

        ##
        ## Request with an invalid operation
        ##
        request.address    = addr
        request.reply_to   = reply
        request.properties = {u'type':u'org.amqp.management', u'name':u'self', u'operation':u'NOT-IMPL'}

        M.put(request)
        M.send()
        M.recv()
        M.get(response)

        self.assertEqual(response.properties['statusCode'], 501)

        M.stop()


    def test_10_semantics_multicast(self):
        addr = self.address+"/multicast.10"
        M1 = self.messenger()
        M2 = self.messenger()
        M3 = self.messenger()
        M4 = self.messenger()


        M1.start()
        M2.start()
        M3.start()
        M4.start()

        M2.subscribe(addr)
        M3.subscribe(addr)
        M4.subscribe(addr)

        tm = Message()
        rm = Message()

        tm.address = addr
        for i in range(100):
            tm.body = {'number': i}
            M1.put(tm)
        M1.send()

        for i in range(100):
            M2.recv(1)
            M2.get(rm)
            self.assertEqual(i, rm.body['number'])

            M3.recv(1)
            M3.get(rm)
            self.assertEqual(i, rm.body['number'])

            M4.recv(1)
            M4.get(rm)
            self.assertEqual(i, rm.body['number'])

        M1.stop()
        M2.stop()
        M3.stop()
        M4.stop()

    def test_11_semantics_closest(self):
        addr = self.address+"/closest.1"
        M1 = self.messenger()
        M2 = self.messenger()
        M3 = self.messenger()
        M4 = self.messenger()


        M1.start()
        M2.start()
        M3.start()
        M4.start()

        M2.subscribe(addr)
        M3.subscribe(addr)
        M4.subscribe(addr)

        tm = Message()
        rm = Message()

        tm.address = addr
        for i in range(30):
            tm.body = {'number': i}
            M1.put(tm)
        M1.send()

        i = 0
        rx_set = []
        for i in range(10):
            M2.recv(1)
            M2.get(rm)
            rx_set.append(rm.body['number'])

            M3.recv(1)
            M3.get(rm)
            rx_set.append(rm.body['number'])

            M4.recv(1)
            M4.get(rm)
            rx_set.append(rm.body['number'])

        self.assertEqual(30, len(rx_set))
        rx_set.sort()
        for i in range(30):
            self.assertEqual(i, rx_set[i])

        M1.stop()
        M2.stop()
        M3.stop()
        M4.stop()

    def test_12_semantics_spread(self):
        addr = self.address+"/spread.1"
        M1 = self.messenger()
        M2 = self.messenger()
        M3 = self.messenger()
        M4 = self.messenger()

        M2.timeout = 0.1
        M3.timeout = 0.1
        M4.timeout = 0.1

        M1.start()
        M2.start()
        M3.start()
        M4.start()

        M2.subscribe(addr)
        M3.subscribe(addr)
        M4.subscribe(addr)

        tm = Message()
        rm = Message()

        tm.address = addr
        for i in range(30):
            tm.body = {'number': i}
            M1.put(tm)
        M1.send()

        i = 0
        rx_set = []
        ca = 0
        cb = 0
        cc = 0

        while len(rx_set) < 30:
            try:
                M2.recv(1)
                M2.get(rm)
                rx_set.append(rm.body['number'])
                ca += 1
            except:
                pass

            try:
                M3.recv(1)
                M3.get(rm)
                rx_set.append(rm.body['number'])
                cb += 1
            except:
                pass

            try:
                M4.recv(1)
                M4.get(rm)
                rx_set.append(rm.body['number'])
                cc += 1
            except:
                pass

        self.assertEqual(30, len(rx_set))
        self.assertTrue(ca > 0)
        self.assertTrue(cb > 0)
        self.assertTrue(cc > 0)

        rx_set.sort()
        for i in range(30):
            self.assertEqual(i, rx_set[i])

        M1.stop()
        M2.stop()
        M3.stop()
        M4.stop()


    def test_13_to_override(self):
        addr = self.address+"/toov/1"
        M1 = self.messenger()
        M2 = self.messenger()

        M1.start()
        M2.start()
        M2.subscribe(addr)

        tm = Message()
        rm = Message()

        tm.address = addr

        ##
        ## Pre-existing TO
        ##
        tm.annotations = {'x-opt-qd.to': 'toov/1'}
        for i in range(10):
            tm.body = {'number': i}
            M1.put(tm)
        M1.send()

        for i in range(10):
            M2.recv(1)
            M2.get(rm)
            self.assertEqual(i, rm.body['number'])
            ma = rm.annotations
            self.assertEqual(ma.__class__, dict)
            self.assertEqual(ma['x-opt-qd.to'], 'toov/1')

        M1.stop()
        M2.stop()

    def test_14_send_settle_mode_settled(self):
        """
        The receiver sets a snd-settle-mode of settle thus indicating that it wants to receive settled messages from
        the sender. This tests make sure that the delivery that comes to the receiver comes as already settled.
        """
        send_settle_mode_test = SndSettleModeTest(self.address)
        send_settle_mode_test.run()
        self.assertTrue(send_settle_mode_test.message_received)
        self.assertTrue(send_settle_mode_test.delivery_already_settled)

    def test_15_excess_deliveries_released(self):
        """
        Message-route a series of deliveries where the receiver provides credit for a subset and
        once received, closes the link.  The remaining deliveries should be released back to the sender.
        """
        test = ExcessDeliveriesReleasedTest(self.address)
        test.run()
        self.assertEqual(None, test.error)

    def test_16_multicast_unsettled(self):
        test = MulticastUnsettledTest(self.address)
        test.run()
        self.assertEqual(None, test.error)

    def test_17_multiframe_presettled(self):
        test = MultiframePresettledTest(self.address)
        test.run()
        self.assertEqual(None, test.error)

    def test_18_released_vs_modified(self):
        test = ReleasedVsModifiedTest(self.address)
        test.run()
        self.assertEqual(None, test.error)

    def test_connection_properties(self):
        connection = BlockingConnection(self.router.addresses[0],
                                        timeout=60,
                                        properties=CONNECTION_PROPERTIES)
        client = SyncRequestResponse(connection)

        node = Node.connect(self.router.addresses[0])

        results = [[{u'connection': u'properties', u'int_property': 6451}], [{}]]

        self.assertEqual(node.query(type='org.apache.qpid.dispatch.connection', attribute_names=['properties']).results,
                         results)

        client.connection.close()


class Timeout(object):
    def __init__(self, parent):
        self.parent = parent

    def on_timer_task(self, event):
        self.parent.timeout()


HELLO_WORLD = "Hello World!"

class SndSettleModeTest(MessagingHandler):
    def __init__(self, address):
        super(SndSettleModeTest, self).__init__()
        self.address = address
        self.sender = None
        self.receiver = None
        self.message_received = False
        self.delivery_already_settled = False

    def on_start(self, event):
        conn = event.container.connect(self.address)
        # The receiver sets link.snd_settle_mode = Link.SND_SETTLED. It wants to receive settled messages
        self.receiver = event.container.create_receiver(conn, "org/apache/dev", options=AtMostOnce())

        # With AtLeastOnce, the sender will not settle.
        self.sender = event.container.create_sender(conn, "org/apache/dev", options=AtLeastOnce())

    def on_sendable(self, event):
        msg = Message(body=HELLO_WORLD)
        event.sender.send(msg)
        event.sender.close()

    def on_message(self, event):
        self.delivery_already_settled = event.delivery.settled
        if HELLO_WORLD == event.message.body:
            self.message_received = True
        else:
            self.message_received = False
        event.connection.close()

    def run(self):
        Container(self).run()


class ExcessDeliveriesReleasedTest(MessagingHandler):
    def __init__(self, address):
        super(ExcessDeliveriesReleasedTest, self).__init__(prefetch=0)
        self.address = address
        self.dest = "closest.EDRtest"
        self.error = None
        self.sender = None
        self.receiver = None
        self.n_sent     = 0
        self.n_received = 0
        self.n_accepted = 0
        self.n_released = 0

    def on_start(self, event):
        conn = event.container.connect(self.address)
        self.sender   = event.container.create_sender(conn, self.dest)
        self.receiver = event.container.create_receiver(conn, self.dest)
        self.receiver.flow(6)

    def on_sendable(self, event):
        for i in range(10 - self.n_sent):
            msg = Message(body=i)
            event.sender.send(msg)
            self.n_sent += 1

    def on_accepted(self, event):
        self.n_accepted += 1

    def on_released(self, event):
        self.n_released += 1
        if self.n_released == 4:
            if self.n_accepted != 6:
                self.error = "Expected 6 accepted, got %d" % self.n_accepted
            if self.n_received != 6:
                self.error = "Expected 6 received, got %d" % self.n_received
            event.connection.close()

    def on_message(self, event):
        self.n_received += 1
        if self.n_received == 6:
            self.receiver.close()

    def run(self):
        Container(self).run()


class MulticastUnsettledTest(MessagingHandler):
    def __init__(self, address):
        super(MulticastUnsettledTest, self).__init__(prefetch=0)
        self.address = address
        self.dest = "multicast.MUtest"
        self.error = None
        self.count      = 10
        self.n_sent     = 0
        self.n_received = 0
        self.n_accepted = 0

    def check_if_done(self):
        if self.n_received == self.count * 2 and self.n_accepted == self.count:
            self.timer.cancel()
            self.conn.close()

    def timeout(self):
        self.error = "Timeout Expired: sent=%d, received=%d, accepted=%d" % (self.n_sent, self.n_received, self.n_accepted)
        self.conn.close()

    def on_start(self, event):
        self.timer     = event.reactor.schedule(5, Timeout(self))
        self.conn      = event.container.connect(self.address)
        self.sender    = event.container.create_sender(self.conn, self.dest)
        self.receiver1 = event.container.create_receiver(self.conn, self.dest, name="A")
        self.receiver2 = event.container.create_receiver(self.conn, self.dest, name="B")
        self.receiver1.flow(self.count)
        self.receiver2.flow(self.count)

    def on_sendable(self, event):
        for i in range(self.count - self.n_sent):
            msg = Message(body=i)
            event.sender.send(msg)
            self.n_sent += 1

    def on_accepted(self, event):
        self.n_accepted += 1
        self.check_if_done()

    def on_message(self, event):
        if not event.delivery.settled:
            self.error = "Received unsettled delivery"
        self.n_received += 1
        self.check_if_done()

    def run(self):
        Container(self).run()


class MultiframePresettledTest(MessagingHandler):
    def __init__(self, address):
        super(MultiframePresettledTest, self).__init__(prefetch=0)
        self.address = address
        self.dest = "closest.MFPtest"
        self.error = None
        self.count      = 10
        self.n_sent     = 0
        self.n_received = 0

        self.body = ""
        for i in range(10000):
            self.body += "0123456789"

    def check_if_done(self):
        if self.n_received == self.count:
            self.timer.cancel()
            self.conn.close()

    def timeout(self):
        self.error = "Timeout Expired: sent=%d, received=%d" % (self.n_sent, self.n_received)
        self.conn.close()

    def on_start(self, event):
        self.timer     = event.reactor.schedule(5, Timeout(self))
        self.conn      = event.container.connect(self.address)
        self.sender    = event.container.create_sender(self.conn, self.dest)
        self.receiver  = event.container.create_receiver(self.conn, self.dest, name="A")
        self.receiver.flow(self.count)

    def on_sendable(self, event):
        for i in range(self.count - self.n_sent):
            msg = Message(body=self.body)
            dlv = event.sender.send(msg)
            dlv.settle()
            self.n_sent += 1

    def on_message(self, event):
        if not event.delivery.settled:
            self.error = "Received unsettled delivery"
        self.n_received += 1
        self.check_if_done()

    def run(self):
        Container(self).run()


class ReleasedVsModifiedTest(MessagingHandler):
    def __init__(self, address):
        super(ReleasedVsModifiedTest, self).__init__(prefetch=0, auto_accept=False)
        self.address = address
        self.dest = "closest.RVMtest"
        self.error = None
        self.count      = 10
        self.accept     = 6
        self.n_sent     = 0
        self.n_received = 0
        self.n_released = 0
        self.n_modified = 0

    def check_if_done(self):
        if self.n_received == self.accept and self.n_released == self.count - self.accept and self.n_modified == self.accept:
            self.timer.cancel()
            self.conn.close()

    def timeout(self):
        self.error = "Timeout Expired: sent=%d, received=%d, released=%d, modified=%d" % \
                     (self.n_sent, self.n_received, self.n_released, self.n_modified)
        self.conn.close()

    def on_start(self, event):
        self.timer     = event.reactor.schedule(5, Timeout(self))
        self.conn      = event.container.connect(self.address)
        self.sender    = event.container.create_sender(self.conn, self.dest)
        self.receiver  = event.container.create_receiver(self.conn, self.dest, name="A")
        self.receiver.flow(self.accept)

    def on_sendable(self, event):
        for i in range(self.count - self.n_sent):
            msg = Message(body="RvM-Test")
            event.sender.send(msg)
            self.n_sent += 1

    def on_message(self, event):
        self.n_received += 1
        if self.n_received == self.accept:
            self.receiver.close()

    def on_released(self, event):
        if event.delivery.remote_state == Delivery.MODIFIED:
            self.n_modified += 1
        else:
            self.n_released += 1
        self.check_if_done()

    def run(self):
        Container(self).run()


if __name__ == '__main__':
    unittest.main(main_module())
