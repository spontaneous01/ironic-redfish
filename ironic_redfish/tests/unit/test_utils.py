# Copyright 2017 Red Hat, Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import os

import mock

from ironic.common import exception
from ironic.tests.unit.db import base as db_base
from ironic.tests.unit.objects import utils as obj_utils

import ironic_redfish
from ironic_redfish import utils as redfish_utils


INFO_DICT = {
    "redfish_address": "https://example.com",
    "redfish_system_id": "/redfish/v1/Systems/FAKESYSTEM",
    "redfish_username": "username",
    "redfish_password": "password"
}


class MockedConnectionError(Exception):
    pass


class MockedResourceNotFoundError(Exception):
    pass


class RedfishUtilsTestCase(db_base.DbTestCase):

    def setUp(self):
        super(RedfishUtilsTestCase, self).setUp()
        # Default configurations
        self.config(enabled_drivers=['pxe_redfish'])
        # Redfish specific configurations
        self.config(connection_attempts=1, group='redfish')
        self.node = obj_utils.create_test_node(
            self.context, driver='pxe_redfish', driver_info=INFO_DICT)
        self.parsed_driver_info = {
            'address': 'https://example.com',
            'system_id': '/redfish/v1/Systems/FAKESYSTEM',
            'username': 'username',
            'password': 'password',
            'verify_ca': True,
            'node_uuid': self.node.uuid
        }

    def test_parse_driver_info(self):
        response = redfish_utils.parse_driver_info(self.node)
        self.assertEqual(self.parsed_driver_info, response)

    def test_parse_driver_info_default_scheme(self):
        self.node.driver_info['redfish_address'] = 'example.com'
        response = redfish_utils.parse_driver_info(self.node)
        self.assertEqual(self.parsed_driver_info, response)

    def test_parse_driver_info_default_scheme_with_port(self):
        self.node.driver_info['redfish_address'] = 'example.com:42'
        self.parsed_driver_info['address'] = 'https://example.com:42'
        response = redfish_utils.parse_driver_info(self.node)
        self.assertEqual(self.parsed_driver_info, response)

    def test_parse_driver_info_missing_info(self):
        for prop in redfish_utils.REQUIRED_PROPERTIES:
            self.node.driver_info = INFO_DICT.copy()
            self.node.driver_info.pop(prop)
            self.assertRaises(exception.MissingParameterValue,
                              redfish_utils.parse_driver_info, self.node)

    def test_parse_driver_info_invalid_address(self):
        for value in ['/banana!', 42]:
            self.node.driver_info['redfish_address'] = value
            self.assertRaisesRegex(exception.InvalidParameterValue,
                                   'Invalid Redfish address',
                                   redfish_utils.parse_driver_info, self.node)

    @mock.patch.object(os.path, 'exists', autospec=True)
    def test_parse_driver_info_path_verify_ca(self, mock_path_exists):
        mock_path_exists.return_value = True
        fake_path = '/path/to/a/valid/CA'
        self.node.driver_info['redfish_verify_ca'] = fake_path
        self.parsed_driver_info['verify_ca'] = fake_path

        response = redfish_utils.parse_driver_info(self.node)
        self.assertEqual(self.parsed_driver_info, response)
        mock_path_exists.assert_called_once_with(fake_path)

    @mock.patch.object(os.path, 'exists', autospec=True)
    def test_parse_driver_info_invalid_path_verify_ca(self, mock_path_exists):
        mock_path_exists.return_value = False
        fake_path = '/this/path/doesnt/exist'
        self.node.driver_info['redfish_verify_ca'] = fake_path
        self.assertRaisesRegex(exception.InvalidParameterValue,
                               'path to a CA_BUNDLE',
                               redfish_utils.parse_driver_info, self.node)
        mock_path_exists.assert_called_once_with(fake_path)

    def test_parse_driver_info_invalid_value_verify_ca(self):
        # Integers are not supported
        self.node.driver_info['redfish_verify_ca'] = 123456
        self.assertRaisesRegex(exception.InvalidParameterValue,
                               'Invalid value type',
                               redfish_utils.parse_driver_info, self.node)

    @mock.patch.object(redfish_utils, 'sushy')
    def test_get_system(self, mock_sushy):
        fake_conn = mock_sushy.Sushy.return_value
        fake_system = fake_conn.get_system.return_value

        response = redfish_utils.get_system(self.node)
        self.assertEqual(fake_system, response)
        fake_conn.get_system.assert_called_once_with(
            '/redfish/v1/Systems/FAKESYSTEM')

    @mock.patch.object(redfish_utils, 'sushy')
    def test_get_system_resource_not_found(self, mock_sushy):
        fake_conn = mock_sushy.Sushy.return_value
        mock_sushy.exceptions.ResourceNotFoundError = (
            MockedResourceNotFoundError)
        fake_conn.get_system.side_effect = MockedResourceNotFoundError()

        self.assertRaises(ironic_redfish.RedfishError,
                          redfish_utils.get_system, self.node)
        fake_conn.get_system.assert_called_once_with(
            '/redfish/v1/Systems/FAKESYSTEM')

    @mock.patch('time.sleep', autospec=True)
    @mock.patch.object(redfish_utils, 'sushy')
    def test_get_system_resource_connection_error_retry(self, mock_sushy,
                                                        mock_sleep):
        # Redfish specific configurations
        self.config(connection_attempts=3, group='redfish')

        fake_conn = mock_sushy.Sushy.return_value
        mock_sushy.exceptions.ResourceNotFoundError = (
            MockedResourceNotFoundError)
        mock_sushy.exceptions.ConnectionError = MockedConnectionError
        fake_conn.get_system.side_effect = MockedConnectionError()

        self.assertRaises(ironic_redfish.RedfishConnectionError,
                          redfish_utils.get_system, self.node)

        expected_get_system_calls = [
            mock.call(self.parsed_driver_info['system_id']),
            mock.call(self.parsed_driver_info['system_id']),
            mock.call(self.parsed_driver_info['system_id']),
        ]
        fake_conn.get_system.assert_has_calls(expected_get_system_calls)
        mock_sleep.assert_called_with(
            redfish_utils.CONF.redfish.connection_retry_interval)
