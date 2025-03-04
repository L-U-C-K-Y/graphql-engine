#!/usr/bin/env python3

import string
import random
from ruamel.yaml import YAML
import json
import graphql
import queue
import requests
import time

import pytest

yaml=YAML(typ='safe', pure=True)

from validate import check_query_f, check_query
from graphql import GraphQLError

def mk_add_remote_q(name, url, headers=None, client_hdrs=False, timeout=None, customization=None):
    return {
        "type": "add_remote_schema",
        "args": {
            "name": name,
            "comment": "testing " + name,
            "definition": {
                "url": url,
                "headers": headers,
                "forward_client_headers": client_hdrs,
                "timeout_seconds": timeout,
                "customization": customization
            }
        }
    }

def type_prefix_customization(type_prefix, mapping={}):
    return { "type_names": {"prefix": type_prefix, "mapping": mapping }}

def mk_update_remote_q(name, url, headers=None, client_hdrs=False, timeout=None, customization=None):
    return {
        "type": "update_remote_schema",
        "args": {
            "name": name,
            "comment": "testing " + name,
            "definition": {
                "url": url,
                "headers": headers,
                "forward_client_headers": client_hdrs,
                "timeout_seconds": timeout,
                "customization": customization
            }
        }
    }

def mk_delete_remote_q(name):
    return {
        "type" : "remove_remote_schema",
        "args" : {
            "name": name
        }
    }

def mk_reload_remote_q(name):
    return {
        "type" : "reload_remote_schema",
        "args" : {
            "name" : name
        }
    }

export_metadata_q = {"type": "export_metadata", "args": {}}

class TestRemoteSchemaBasic:
    """ basic => no hasura tables are tracked """

    teardown = {"type": "clear_metadata", "args": {}}
    dir = 'queries/remote_schemas'

    @pytest.fixture(autouse=True)
    def transact(self, request, hge_ctx):
        config = request.config
        # This is needed for supporting server upgrade tests
        # Some marked tests in this class will be run as server upgrade tests
        if not config.getoption('--skip-schema-setup'):
            q = mk_add_remote_q('simple 1', 'http://localhost:5000/hello-graphql')
            st_code, resp = hge_ctx.v1q(q)
            assert st_code == 200, resp
        yield
        if request.session.testsfailed > 0 or not config.getoption('--skip-schema-teardown'):
            hge_ctx.v1q(self.teardown)

    def test_add_schema(self, hge_ctx):
        """ check if the remote schema is added in the metadata """
        st_code, resp = hge_ctx.v1q(export_metadata_q)
        assert st_code == 200, resp
        assert resp['remote_schemas'][0]['name'] == "simple 1"

    def test_update_schema_with_no_url_change(self, hge_ctx):
        """ call update_remote_schema API and check the details stored in metadata """
        q = mk_update_remote_q('simple 1', 'http://localhost:5000/hello-graphql', None, True, 120)
        st_code, resp = hge_ctx.v1q(q)
        assert st_code == 200, resp

        st_code, resp = hge_ctx.v1q(export_metadata_q)
        assert st_code == 200, resp
        assert resp['remote_schemas'][0]['name'] == "simple 1"
        assert resp['remote_schemas'][0]['definition']['timeout_seconds'] == 120
        assert resp['remote_schemas'][0]['definition']['forward_client_headers'] == True

        """ revert to original config for remote schema """
        q = mk_update_remote_q('simple 1', 'http://localhost:5000/hello-graphql', None, False, 60)
        st_code, resp = hge_ctx.v1q(q)
        assert st_code == 200, resp

    def test_update_schema_with_url_change(self, hge_ctx):
        """ call update_remote_schema API and check the details stored in metadata """
        q = mk_update_remote_q('simple 1', 'http://localhost:5000/user-graphql', None, True, 80)
        st_code, resp = hge_ctx.v1q(q)
        # This should succeed since there isn't any conflicting relations or permissions set up
        assert st_code == 200, resp

        st_code, resp = hge_ctx.v1q(export_metadata_q)
        assert st_code == 200, resp
        assert resp['remote_schemas'][0]['name'] == "simple 1"
        assert resp['remote_schemas'][0]['definition']['url'] == 'http://localhost:5000/user-graphql'
        assert resp['remote_schemas'][0]['definition']['timeout_seconds'] == 80
        assert resp['remote_schemas'][0]['definition']['forward_client_headers'] == True

        """ revert to original config for remote schema """
        q = mk_update_remote_q('simple 1', 'http://localhost:5000/hello-graphql', None, False, 60)
        st_code, resp = hge_ctx.v1q(q)
        assert st_code == 200, resp

    def test_update_schema_with_customization_change(self, hge_ctx):
        """ call update_remote_schema API and check the details stored in metadata """
        customization = {'type_names': { 'prefix': 'Foo', 'mapping': {'String': 'MyString'}}, 'field_names': [{'parent_type': 'Hello', 'prefix': 'my_', 'mapping': {}}]}
        q = mk_update_remote_q('simple 1', 'http://localhost:5000/hello-graphql', None, False, 60, customization=customization)
        st_code, resp = hge_ctx.v1q(q)
        # This should succeed since there isn't any conflicting relations or permissions set up
        assert st_code == 200, resp

        st_code, resp = hge_ctx.v1q(export_metadata_q)
        assert st_code == 200, resp
        assert resp['remote_schemas'][0]['name'] == "simple 1"
        assert resp['remote_schemas'][0]['definition']['url'] == 'http://localhost:5000/hello-graphql'
        assert resp['remote_schemas'][0]['definition']['timeout_seconds'] == 60
        assert resp['remote_schemas'][0]['definition']['customization'] == customization

        with open('queries/graphql_introspection/introspection.yaml') as f:
            query = yaml.load(f)
        resp, _ = check_query(hge_ctx, query)
        assert check_introspection_result(resp, ['MyString'], ['my_hello'])

        check_query_f(hge_ctx, self.dir + '/basic_query_customized.yaml')

        """ revert to original config for remote schema """
        q = mk_update_remote_q('simple 1', 'http://localhost:5000/hello-graphql', None, False, 60)
        st_code, resp = hge_ctx.v1q(q)
        assert st_code == 200, resp

        st_code, resp = hge_ctx.v1q(export_metadata_q)
        assert st_code == 200, resp
        assert 'customization' not in resp['remote_schemas'][0]['definition']

    def test_update_schema_with_customization_change_invalid(self, hge_ctx):
        """ call update_remote_schema API and check the details stored in metadata """
        customization = {'type_names': { 'mapping': {'String': 'Foo', 'Hello': 'Foo'} } }
        q = mk_update_remote_q('simple 1', 'http://localhost:5000/hello-graphql', None, False, 60, customization=customization)
        st_code, resp = hge_ctx.v1q(q)
        assert st_code == 400, resp
        assert resp['error'] == 'Inconsistent object: Type name mappings are not distinct; the following types appear more than once: "Foo"'

        """ revert to original config for remote schema """
        q = mk_update_remote_q('simple 1', 'http://localhost:5000/hello-graphql', None, False, 60)
        st_code, resp = hge_ctx.v1q(q)
        assert st_code == 200, resp

    @pytest.mark.allow_server_upgrade_test
    def test_introspection(self, hge_ctx):
        #check_query_f(hge_ctx, 'queries/graphql_introspection/introspection.yaml')
        with open('queries/graphql_introspection/introspection.yaml') as f:
            query = yaml.load(f)
        resp, _ = check_query(hge_ctx, query)
        assert check_introspection_result(resp, ['String'], ['hello'])

    @pytest.mark.allow_server_upgrade_test
    def test_introspection_as_user(self, hge_ctx):
        check_query_f(hge_ctx, 'queries/graphql_introspection/introspection_user_role.yaml')

    @pytest.mark.allow_server_upgrade_test
    def test_remote_query(self, hge_ctx):
        check_query_f(hge_ctx, self.dir + '/basic_query.yaml')

    def test_remote_subscription(self, hge_ctx):
        check_query_f(hge_ctx, self.dir + '/basic_subscription_not_supported.yaml')

    def test_add_schema_conflicts(self, hge_ctx):
        """add 2 remote schemas with same node or types"""
        q = mk_add_remote_q('simple 2', 'http://localhost:5000/hello-graphql')
        st_code, resp = hge_ctx.v1q(q)
        assert st_code == 400
        assert resp['code'] == 'unexpected'

    @pytest.mark.allow_server_upgrade_test
    def test_remove_schema_error(self, hge_ctx):
        """remove remote schema which is not added"""
        q = mk_delete_remote_q('random name')
        st_code, resp = hge_ctx.v1q(q)
        assert st_code == 400
        assert resp['code'] == 'not-exists'

    @pytest.mark.allow_server_upgrade_test
    def test_reload_remote_schema(self, hge_ctx):
        """reload a remote schema"""
        q = mk_reload_remote_q('simple 1')
        st_code, resp = hge_ctx.v1q(q)
        assert st_code == 200

    @pytest.mark.allow_server_upgrade_test
    def test_add_second_remote_schema(self, hge_ctx):
        """add 2 remote schemas with different node and types"""
        q = mk_add_remote_q('my remote', 'http://localhost:5000/user-graphql')
        st_code, resp = hge_ctx.v1q(q)
        assert st_code == 200, resp
        st_code, resp = hge_ctx.v1q(mk_delete_remote_q('my remote'))
        assert st_code == 200, resp

    @pytest.mark.allow_server_upgrade_test
    def test_add_remote_schema_with_interfaces(self, hge_ctx):
        """add a remote schema with interfaces in it"""
        q = mk_add_remote_q('my remote interface one', 'http://localhost:5000/character-iface-graphql')
        st_code, resp = hge_ctx.v1q(q)
        assert st_code == 200, resp
        check_query_f(hge_ctx, self.dir + '/character_interface_query.yaml')
        st_code, resp = hge_ctx.v1q(mk_delete_remote_q('my remote interface one'))
        assert st_code == 200, resp

    def test_add_remote_schema_with_interface_err_empty_fields_list(self, hge_ctx):
        """add a remote schema with an interface having no fields"""
        check_query_f(hge_ctx, self.dir + '/add_remote_schema_with_iface_err_empty_fields_list.yaml')

    def test_add_remote_schema_err_unknown_interface(self, hge_ctx):
        """add a remote schema with an interface having no fields"""
        check_query_f(hge_ctx, self.dir + '/add_remote_schema_err_unknown_interface.yaml')

    def test_add_remote_schema_with_interface_err_missing_field(self, hge_ctx):
        """ add a remote schema where an object implementing an interface does
        not have a field defined in the interface """
        check_query_f(hge_ctx, self.dir + '/add_remote_schema_err_missing_field.yaml')

    def test_add_remote_schema_with_interface_err_wrong_field_type(self, hge_ctx):
        """add a remote schema where an object implementing an interface have a
        field with the same name as in the interface, but of different type"""
        check_query_f(hge_ctx, self.dir + '/add_remote_schema_with_iface_err_wrong_field_type.yaml')

    def test_add_remote_schema_with_interface_err_missing_arg(self, hge_ctx):
        """add a remote schema where a field of an object implementing an
        interface does not have the argument defined in the same field of
        interface"""
        check_query_f(hge_ctx, self.dir + '/add_remote_schema_err_missing_arg.yaml')

    def test_add_remote_schema_with_interface_err_wrong_arg_type(self, hge_ctx):
        """add a remote schema where the argument of a field of an object
        implementing the interface does not have the same type as the argument
        defined in the field of interface"""
        check_query_f(hge_ctx, self.dir + '/add_remote_schema_iface_err_wrong_arg_type.yaml')

    def test_add_remote_schema_with_interface_err_extra_non_null_arg(self, hge_ctx):
        """add a remote schema with a field of an object implementing interface
        having extra non_null argument"""
        check_query_f(hge_ctx, self.dir + '/add_remote_schema_with_iface_err_extra_non_null_arg.yaml')

    @pytest.mark.allow_server_upgrade_test
    def test_add_remote_schema_with_union(self, hge_ctx):
        """add a remote schema with union in it"""
        q = mk_add_remote_q('my remote union one', 'http://localhost:5000/union-graphql')
        st_code, resp = hge_ctx.v1q(q)
        assert st_code == 200, resp
        check_query_f(hge_ctx, self.dir + '/search_union_type_query.yaml')
        hge_ctx.v1q({"type": "remove_remote_schema", "args": {"name": "my remote union one"}})
        assert st_code == 200, resp

    def test_add_remote_schema_with_union_err_no_member_types(self, hge_ctx):
        """add a remote schema with a union having no member types"""
        check_query_f(hge_ctx, self.dir + '/add_remote_schema_with_union_err_no_member_types.yaml')

    def test_add_remote_schema_with_union_err_unkown_types(self, hge_ctx):
        """add a remote schema with a union having unknown types as memberTypes"""
        check_query_f(hge_ctx, self.dir + '/add_remote_schema_with_union_err_unknown_types.yaml')

    def test_add_remote_schema_with_union_err_subtype_iface(self, hge_ctx):
        """add a remote schema with a union having interface as a memberType"""
        check_query_f(hge_ctx, self.dir + '/add_remote_schema_with_union_err_member_type_interface.yaml')

    def test_add_remote_schema_with_union_err_wrapped_type(self, hge_ctx):
        """add a remote schema with error in spec for union"""
        check_query_f(hge_ctx, self.dir + '/add_remote_schema_with_union_err_wrapped_type.yaml')

    def test_bulk_remove_add_remote_schema(self, hge_ctx):
        st_code, resp = hge_ctx.v1q_f(self.dir + '/basic_bulk_remove_add.yaml')
        assert st_code == 200, resp

class TestRemoteSchemaBasicExtensions:
    """ basic => no hasura tables are tracked """

    teardown = {"type": "clear_metadata", "args": {}}
    dir = 'queries/remote_schemas'

    @pytest.fixture(autouse=True)
    def transact(self, request, hge_ctx):
        config = request.config
        # This is needed for supporting server upgrade tests
        # Some marked tests in this class will be run as server upgrade tests
        if not config.getoption('--skip-schema-setup'):
            q = mk_add_remote_q('simple 1', 'http://localhost:5000/hello-graphql-extensions')
            st_code, resp = hge_ctx.v1q(q)
            assert st_code == 200, resp
        yield
        if request.session.testsfailed > 0 or not config.getoption('--skip-schema-teardown'):
            hge_ctx.v1q(self.teardown)

    def test_remote_query(self, hge_ctx):
        check_query_f(hge_ctx, self.dir + '/basic_query.yaml')


class TestAddRemoteSchemaTbls:
    """ tests with adding a table in hasura """

    dir = 'queries/remote_schemas'

    @pytest.fixture(autouse=True)
    def transact(self, hge_ctx):
        st_code, resp = hge_ctx.v1q_f('queries/remote_schemas/tbls_setup.yaml')
        assert st_code == 200, resp
        yield
        st_code, resp = hge_ctx.v1q_f('queries/remote_schemas/tbls_teardown.yaml')
        assert st_code == 200, resp

    @pytest.mark.allow_server_upgrade_test
    def test_add_schema(self, hge_ctx):
        """ check if the remote schema is added in the metadata """
        st_code, resp = hge_ctx.v1q(export_metadata_q)
        assert st_code == 200, resp
        assert resp['remote_schemas'][0]['name'] == "simple2-graphql"

    def test_add_schema_conflicts_with_tables(self, hge_ctx):
        """add remote schema which conflicts with hasura tables"""
        q = mk_add_remote_q('simple2', 'http://localhost:5000/hello-graphql')
        st_code, resp = hge_ctx.v1q(q)
        assert st_code == 400
        assert resp['code'] == 'invalid-configuration'

    @pytest.mark.allow_server_upgrade_test
    def test_add_second_remote_schema(self, hge_ctx):
        """add 2 remote schemas with different node and types"""
        q = mk_add_remote_q('my remote2', 'http://localhost:5000/country-graphql')
        st_code, resp = hge_ctx.v1q(q)
        assert st_code == 200, resp
        hge_ctx.v1q({"type": "remove_remote_schema", "args": {"name": "my remote2"}})
        assert st_code == 200, resp

    def test_remote_query(self, hge_ctx):
        check_query_f(hge_ctx, self.dir + '/simple2_query.yaml')

    def test_remote_mutation(self, hge_ctx):
        check_query_f(hge_ctx, self.dir + '/simple2_mutation.yaml')

    @pytest.mark.allow_server_upgrade_test
    def test_add_conflicting_table(self, hge_ctx):
        st_code, resp = hge_ctx.v1q_f(self.dir + '/create_conflicting_table.yaml')
        assert st_code == 400
        assert resp['code'] == 'remote-schema-conflicts'
        # Drop "user" table which is created in the previous test
        st_code, resp = hge_ctx.v1q_f(self.dir + '/drop_user_table.yaml')
        assert st_code == 200, resp

    def test_introspection(self, hge_ctx):
        with open('queries/graphql_introspection/introspection.yaml') as f:
            query = yaml.load(f)
        resp, _ = check_query(hge_ctx, query)
        assert check_introspection_result(resp, ['User', 'hello'], ['user', 'hello'])

    def test_add_schema_duplicate_name(self, hge_ctx):
        q = mk_add_remote_q('simple2-graphql', 'http://localhost:5000/country-graphql')
        st_code, resp = hge_ctx.v1q(q)
        assert st_code == 400, resp
        assert resp['code'] == 'already-exists'

    @pytest.mark.allow_server_upgrade_test
    def test_add_schema_same_type_containing_same_scalar(self, hge_ctx):
        """
        test types get merged when remote schema has type with same name and
        same structure + a same custom scalar
        """
        st_code, resp = hge_ctx.v1q_f(self.dir + '/person_table.yaml')
        assert st_code == 200, resp
        q = mk_add_remote_q('person-graphql', 'http://localhost:5000/person-graphql')

        st_code, resp = hge_ctx.v1q(q)
        assert st_code == 200, resp
        st_code, resp = hge_ctx.v1q_f(self.dir + '/drop_person_table.yaml')
        assert st_code == 200, resp
        hge_ctx.v1q({"type": "remove_remote_schema", "args": {"name": "person-graphql"}})
        assert st_code == 200, resp

    @pytest.mark.allow_server_upgrade_test
    def test_remote_schema_forward_headers(self, hge_ctx):
        """
        test headers from client and conf and resolved info gets passed
        correctly to remote schema, and no duplicates are sent. this test just
        tests if the remote schema returns success or not. checking of header
        duplicate logic is in the remote schema server
        """
        conf_hdrs = [{'name': 'x-hasura-test', 'value': 'abcd'}]
        add_remote = mk_add_remote_q('header-graphql',
                                     'http://localhost:5000/header-graphql',
                                     headers=conf_hdrs, client_hdrs=True)
        st_code, resp = hge_ctx.v1q(add_remote)
        assert st_code == 200, resp
        q = {'query': '{ wassup }'}
        hdrs = {
            'x-hasura-test': 'xyzz',
            'x-hasura-role': 'user',
            'x-hasura-user-id': 'abcd1234',
            'content-type': 'application/json',
            'Authorization': 'Bearer abcdef',
        }
        if hge_ctx.hge_key:
            hdrs['x-hasura-admin-secret'] = hge_ctx.hge_key

        resp = hge_ctx.http.post(hge_ctx.hge_url+'/v1alpha1/graphql', json=q,
                                 headers=hdrs)
        print(resp.status_code, resp.json())
        assert resp.status_code == 200
        res = resp.json()
        assert 'data' in res
        assert res['data']['wassup'] == 'Hello world'

        hge_ctx.v1q({'type': 'remove_remote_schema',
                     'args': {'name': 'header-graphql'}})
        assert st_code == 200, resp


class TestRemoteSchemaQueriesOverWebsocket:
    dir = 'queries/remote_schemas'
    teardown = {"type": "clear_metadata", "args": {}}

    @pytest.fixture(autouse=True)
    def transact(self, hge_ctx, ws_client):
        st_code, resp = hge_ctx.v1q_f('queries/remote_schemas/tbls_setup.yaml')
        assert st_code == 200, resp
        ws_client.init_as_admin()
        yield
        # teardown
        st_code, resp = hge_ctx.v1q_f('queries/remote_schemas/tbls_teardown.yaml')
        assert st_code == 200, resp
        st_code, resp = hge_ctx.v1q(self.teardown)
        assert st_code == 200, resp

    @pytest.mark.allow_server_upgrade_test
    def test_remote_query(self, ws_client):
        query = """
        query {
          user(id: 2) {
            id
            username
          }
        }
        """
        query_id = ws_client.gen_id()
        resp = ws_client.send_query({'query': query}, query_id=query_id,
                                    timeout=5)
        try:
            ev = next(resp)
            assert ev['type'] == 'data' and ev['id'] == query_id, ev
            assert ev['payload']['data']['user']['username'] == 'john'
        finally:
            ws_client.stop(query_id)

    @pytest.mark.allow_server_upgrade_test
    def test_remote_query_error(self, ws_client):
        query = """
        query {
          user(id: 2) {
            generateError
            username
          }
        }
        """
        query_id = ws_client.gen_id()
        resp = ws_client.send_query({'query': query}, query_id=query_id,
                                    timeout=5)
        try:
            ev = next(resp)
            print(ev)
            assert ev['type'] == 'data' and ev['id'] == query_id, ev
            assert 'errors' in ev['payload']
            assert ev['payload']['errors'][0]['message'] == \
                'Cannot query field "generateError" on type "User".'
        finally:
            ws_client.stop(query_id)

    @pytest.mark.allow_server_upgrade_test
    def test_remote_mutation(self, ws_client):
        query = """
        mutation {
          createUser(id: 42, username: "foobar") {
            user {
              id
              username
            }
          }
        }
        """
        query_id = ws_client.gen_id()
        resp = ws_client.send_query({'query': query}, query_id=query_id,
                                    timeout=5)
        try:
            ev = next(resp)
            assert ev['type'] == 'data' and ev['id'] == query_id, ev
            assert ev['payload']['data']['createUser']['user']['id'] == 42
            assert ev['payload']['data']['createUser']['user']['username'] == 'foobar'
        finally:
            ws_client.stop(query_id)


class TestRemoteSchemaResponseHeaders():
    teardown = {"type": "clear_metadata", "args": {}}
    dir = 'queries/remote_schemas'

    @pytest.fixture(autouse=True)
    def transact(self, hge_ctx):
        q = mk_add_remote_q('sample-auth', 'http://localhost:5000/auth-graphql')
        st_code, resp = hge_ctx.v1q(q)
        assert st_code == 200, resp
        yield
        hge_ctx.v1q(self.teardown)

    @pytest.mark.allow_server_upgrade_test
    def test_response_headers_from_remote(self, hge_ctx):
        headers = {}
        if hge_ctx.hge_key:
            headers = {'x-hasura-admin-secret': hge_ctx.hge_key}
        q = {'query': 'query { hello (arg: "me") }'}
        resp = hge_ctx.http.post(hge_ctx.hge_url + '/v1/graphql', json=q,
                                 headers=headers)
        assert resp.status_code == 200
        assert ('Set-Cookie' in resp.headers and
                resp.headers['Set-Cookie'] == 'abcd')
        res = resp.json()
        assert res['data']['hello'] == "Hello me"


class TestAddRemoteSchemaCompareRootQueryFields:

    remote = 'http://localhost:5000/default-value-echo-graphql'

    @pytest.fixture(autouse=True)
    def transact(self, hge_ctx):
        st_code, resp = hge_ctx.v1q(mk_add_remote_q('default_value_test', self.remote))
        assert st_code == 200, resp
        yield
        st_code, resp = hge_ctx.v1q(mk_delete_remote_q('default_value_test'))
        assert st_code == 200, resp

    @pytest.mark.allow_server_upgrade_test
    def test_schema_check_arg_default_values_and_field_and_arg_types(self, hge_ctx):
        with open('queries/graphql_introspection/introspection.yaml') as f:
            query = yaml.load(f)
        introspect_hasura, _ = check_query(hge_ctx, query)
        resp = requests.post(
            self.remote,
            json=query['query']
        )
        introspect_remote = resp.json()
        assert resp.status_code == 200, introspect_remote
        remote_root_ty_info = get_query_root_info(introspect_remote)
        hasura_root_ty_info = get_query_root_info(introspect_hasura)
        has_fld = dict()

        for fldR in remote_root_ty_info['fields']:
            has_fld[fldR['name']] = False
            for fldH in get_fld_by_name(hasura_root_ty_info, fldR['name']):
                has_fld[fldR['name']] = True
                compare_flds(fldH, fldR)
            assert has_fld[fldR['name']], 'Field ' + fldR['name'] + ' in the remote shema root query type not found in Hasura schema'

class TestRemoteSchemaTimeout:
    dir = 'queries/remote_schemas'
    teardown = {"type": "clear_metadata", "args": {}}

    @pytest.fixture(autouse=True)
    def transact(self, hge_ctx):
        q = mk_add_remote_q('simple 1', 'http://localhost:5000/hello-graphql', timeout = 5)
        st_code, resp = hge_ctx.v1q(q)
        assert st_code == 200, resp
        yield
        hge_ctx.v1q(self.teardown)

    @pytest.mark.allow_server_upgrade_test
    def test_remote_query_timeout(self, hge_ctx):
        check_query_f(hge_ctx, self.dir + '/basic_timeout_query.yaml')
        # wait for graphql server to finish else teardown throws
        time.sleep(6)

#    def test_remote_query_variables(self, hge_ctx):
#        pass
#    def test_add_schema_url_from_env(self, hge_ctx):
#        pass
#    def test_add_schema_header_from_env(self, hge_ctx):
#        pass


def _map(f, l):
    return list(map(f, l))

def _filter(f, l):
    return list(filter(f, l))

def get_query_root_info(res):
    root_ty_name = res['data']['__schema']['queryType']['name']
    return _filter(lambda ty: ty['name'] == root_ty_name, get_types(res))[0]

def get_types(res):
    return res['data']['__schema']['types']

def check_introspection_result(res, types, node_names):
    all_types = _map(lambda t: t['name'], res['data']['__schema']['types'])
    print(all_types)
    q_root = _filter(lambda t: t['name'] == 'query_root',
                     res['data']['__schema']['types'])[0]
    all_nodes = _map(lambda f: f['name'], q_root['fields'])
    print(all_nodes)

    satisfy_ty = True
    satisfy_node = True

    for ty_name in types:
        if ty_name not in all_types:
            satisfy_ty = False

    for nn in node_names:
        if nn not in all_nodes:
            satisfy_node = False

    return satisfy_node and satisfy_ty

def get_fld_by_name(ty, fldName):
    return _filter(lambda f: f['name'] == fldName, ty['fields'])

def get_arg_by_name(fld, argName):
    return _filter(lambda a: a['name'] == argName, fld['args'])

def compare_args(arg_path, argH, argR):
    assert argR['type'] == argH['type'], yaml.dump({
        'error' : 'Types do not match for arg ' + arg_path,
        'remote_type' : argR['type'],
        'hasura_type' : argH['type']
    })
    compare_default_value(argR['defaultValue'], argH['defaultValue'])

# There doesn't seem to be any Python code that can correctly compare GraphQL
# 'Value's for equality. So we try to do it here.
def compare_default_value(valH, valR):
    a = graphql.parse_value(valH)
    b = graphql.parse_value(valR)
    if a == b:
        return True
    for field in a.fields:
        assert field in b.fields
    for field in b.fields:
        assert field in a.fields

def compare_flds(fldH, fldR):
    assert fldH['type'] == fldR['type'], yaml.dump({
        'error' : 'Types do not match for fld ' + fldH['name'],
        'remote_type' : fldR['type'],
        'hasura_type' : fldH['type']
    })
    has_arg = dict()
    for argR in fldR['args']:
        arg_path = fldR['name'] + '(' + argR['name'] + ':)'
        has_arg[arg_path] = False
        for argH in get_arg_by_name(fldH, argR['name']):
            has_arg[arg_path] = True
            compare_args(arg_path, argH, argR)
        assert has_arg[arg_path], 'Argument ' + arg_path + ' in the remote schema root query type not found in Hasura schema'

reload_metadata_q = {
    'type': 'reload_metadata',
    "args": {
        "reload_remote_schemas": True
    }
}

get_inconsistent_metadata_q = {
    'type': 'get_inconsistent_metadata',
    'args': {}
}

class TestRemoteSchemaReload:

    def test_inconsistent_remote_schema_reload_metadata(self, gql_server, hge_ctx):
        # Add remote schema
        st_code, resp = hge_ctx.v1q(mk_add_remote_q('simple 1', 'http://127.0.0.1:5991/hello-graphql'))
        assert st_code == 200, resp
        # stop remote graphql server
        gql_server.stop_server()
        # Reload metadata with remote schemas
        st_code, resp = hge_ctx.v1q(reload_metadata_q)
        assert st_code == 200, resp
        # Check if the remote schema present in inconsistent metadata
        assert resp['is_consistent'] == False, resp
        assert resp['inconsistent_objects'][0]['type'] == 'remote_schema', resp
        # Restart remote graphql server
        gql_server.start_server()
        # Reload the inconsistent remote schema
        st_code, resp = hge_ctx.v1q(mk_reload_remote_q('simple 1'))
        assert st_code == 200, resp
        # Check if metadata is consistent
        st_code, resp = hge_ctx.v1q(get_inconsistent_metadata_q)
        assert st_code == 200, resp
        assert resp['is_consistent'] == True, resp
        # Delete remote schema
        st_code, resp = hge_ctx.v1q(mk_delete_remote_q('simple 1'))
        assert st_code == 200, resp

@pytest.mark.usefixtures('per_class_tests_db_state')
class TestValidateRemoteSchemaQuery:

    @classmethod
    def dir(cls):
        return "queries/remote_schemas/validation/"

    def test_remote_schema_argument_validation(self, hge_ctx):
        """ test to check that the graphql-engine throws an validation error
            when an remote object is queried with an unknown argument  """
        check_query_f(hge_ctx, self.dir() + '/argument_validation.yaml')

    def test_remote_schema_field_validation(self, hge_ctx):
        """ test to check that the graphql-engine throws an validation error
            when an remote object is queried with an unknown field  """
        check_query_f(hge_ctx, self.dir() + '/field_validation.yaml')

class TestRemoteSchemaTypePrefix:
    """ basic => no hasura tables are tracked """

    teardown = {"type": "clear_metadata", "args": {}}
    dir = 'queries/remote_schemas'

    @pytest.fixture(autouse=True)
    def transact(self, request, hge_ctx):
        config = request.config
        # This is needed for supporting server upgrade tests
        # Some marked tests in this class will be run as server upgrade tests
        if not config.getoption('--skip-schema-setup'):
            q = mk_add_remote_q('simple 2', 'http://localhost:5000/user-graphql', customization=type_prefix_customization("Foo"))
            st_code, resp = hge_ctx.v1q(q)
            assert st_code == 200, resp
        yield
        if request.session.testsfailed > 0 or not config.getoption('--skip-schema-teardown'):
            hge_ctx.v1q(self.teardown)

    def test_add_schema(self, hge_ctx):
        """ check if the remote schema is added in the metadata """
        st_code, resp = hge_ctx.v1q(export_metadata_q)
        assert st_code == 200, resp
        assert resp['remote_schemas'][0]['name'] == "simple 2"
        # assert resp['remote_schemas'][0]['definition']['type_prefix'] == "foo"

    @pytest.mark.allow_server_upgrade_test
    def test_introspection(self, hge_ctx):
        #check_query_f(hge_ctx, 'queries/graphql_introspection/introspection.yaml')
        with open('queries/graphql_introspection/introspection.yaml') as f:
            query = yaml.load(f)
        resp, _ = check_query(hge_ctx, query)
        assert check_introspection_result(resp, ['FooUser', 'FooCreateUser', 'FooCreateUserInputObject', 'FooUserDetailsInput'], ['user', 'allUsers'])

class TestValidateRemoteSchemaTypePrefixQuery:

    teardown = {"type": "clear_metadata", "args": {}}

    @pytest.fixture(autouse=True)
    def transact(self, request, hge_ctx):
        config = request.config
        if not config.getoption('--skip-schema-setup'):
            q = mk_add_remote_q('character-foo', 'http://localhost:5000/character-iface-graphql', customization=type_prefix_customization("Foo"))
            st_code, resp = hge_ctx.v1q(q)
            assert st_code == 200, resp
        yield
        if request.session.testsfailed > 0 or not config.getoption('--skip-schema-teardown'):
            hge_ctx.v1q(self.teardown)

    @classmethod
    def dir(cls):
        return "queries/remote_schemas/validation/"

    def test_remote_schema_type_prefix_validation(self, hge_ctx):
        check_query_f(hge_ctx, self.dir() + '/type_prefix_validation.yaml')

class TestValidateRemoteSchemaFieldPrefixQuery:

    teardown = {"type": "clear_metadata", "args": {}}

    @pytest.fixture(autouse=True)
    def transact(self, request, hge_ctx):
        config = request.config
        if not config.getoption('--skip-schema-setup'):
            customization = { "field_names": [{"parent_type": "Character", "prefix": "foo_"},{"parent_type": "Human", "prefix": "foo_"},{"parent_type": "Droid", "prefix": "foo_"}] }
            q = mk_add_remote_q('character-foo', 'http://localhost:5000/character-iface-graphql', customization=customization)
            st_code, resp = hge_ctx.v1q(q)
            assert st_code == 200, resp
        yield
        if request.session.testsfailed > 0 or not config.getoption('--skip-schema-teardown'):
            hge_ctx.v1q(self.teardown)

    @classmethod
    def dir(cls):
        return "queries/remote_schemas/validation/"

    def test_remote_schema_field_prefix_validation(self, hge_ctx):
        check_query_f(hge_ctx, self.dir() + '/field_prefix_validation.yaml')

class TestValidateRemoteSchemaCustomization:
    @classmethod
    def dir(cls):
        return "queries/remote_schemas/validation/"

    def test_remote_schema_interface_field_validation(self, hge_ctx):
        check_query_f(hge_ctx, self.dir() + '/interface_field_validation.yaml')

class TestValidateRemoteSchemaNamespaceQuery:

    teardown = {"type": "clear_metadata", "args": {}}

    @pytest.fixture(autouse=True)
    def transact(self, request, hge_ctx):
        config = request.config
        if not config.getoption('--skip-schema-setup'):
            customization = { "root_fields_namespace": "foo" }
            q = mk_add_remote_q('character-foo', 'http://localhost:5000/character-iface-graphql', customization=customization)
            st_code, resp = hge_ctx.v1q(q)
            assert st_code == 200, resp
        yield
        if request.session.testsfailed > 0 or not config.getoption('--skip-schema-teardown'):
            hge_ctx.v1q(self.teardown)

    @classmethod
    def dir(cls):
        return "queries/remote_schemas/validation/"

    def test_remote_schema_namespace_validation(self, hge_ctx):
        check_query_f(hge_ctx, self.dir() + '/namespace_validation.yaml')

class TestValidateRemoteSchemaCustomizeAllTheThings:

    teardown = {"type": "clear_metadata", "args": {}}

    @pytest.fixture(autouse=True)
    def transact(self, request, hge_ctx):
        config = request.config
        if not config.getoption('--skip-schema-setup'):
            customization = {
                "root_fields_namespace": "star_wars",
                "type_names": {"prefix": "Foo", "suffix": "_x", "mapping": { "Droid": "Android", "Int": "MyInt"}},
                "field_names": [
                        {"parent_type": "Character", "prefix": "foo_", "suffix": "_f", "mapping": {"id": "ident"}},
                        {"parent_type": "Human", "mapping": {"id": "ident", "name": "foo_name_f", "droid": "android"}},
                        {"parent_type": "Droid", "prefix": "foo_", "suffix": "_f", "mapping": {"id": "ident"}},
                        {"parent_type": "CharacterIFaceQuery", "prefix": "super_" }
                    ]
                }
            q = mk_add_remote_q('character-foo', 'http://localhost:5000/character-iface-graphql', customization=customization)
            st_code, resp = hge_ctx.v1q(q)
            assert st_code == 200, resp
        yield
        if request.session.testsfailed > 0 or not config.getoption('--skip-schema-teardown'):
            hge_ctx.v1q(self.teardown)

    @classmethod
    def dir(cls):
        return "queries/remote_schemas/validation/"

    def test_remote_schema_customize_all_the_things(self, hge_ctx):
        check_query_f(hge_ctx, self.dir() + '/customize_all_the_things.yaml')

class TestRemoteSchemaRequestPayload:
    dir = 'queries/remote_schemas'
    teardown = {"type": "clear_metadata", "args": {}}

    @pytest.fixture(autouse=True)
    def transact(self, hge_ctx):
        q = mk_add_remote_q('echo request', 'http://localhost:5000/hello-echo-request-graphql')
        st_code, resp = hge_ctx.v1q(q)
        assert st_code == 200, resp
        yield
        hge_ctx.v1q(self.teardown)

    @pytest.mark.allow_server_upgrade_test
    def test_remote_schema_operation_name_in_response(self, hge_ctx):

        with open('queries/remote_schemas/basic_query_with_op_name.yaml') as f:
            query = yaml.load(f)
        resp, _ = check_query(hge_ctx, query)

        assert resp['data']['hello']['operationName'] == "HelloMe"