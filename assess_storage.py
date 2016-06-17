#!/usr/bin/env python
"""Assess juju charm storage."""

from __future__ import print_function
import os

import argparse
import copy
import json
import logging
import sys

from deploy_stack import (
    BootstrapManager,
)
from jujucharm import Charm
from utility import (
    add_basic_testing_arguments,
    configure_logging,
    JujuAssertionError,
    local_charm_path,
    temp_dir,
)


__metaclass__ = type


log = logging.getLogger("assess_storage")


storage_pool_details = {
    "loopy":
        {
            "provider": "loop",
            "attrs":
                {
                    "size": "1G"
                }},
    "rooty":
        {
            "provider": "rootfs",
            "attrs":
                {
                    "size": "1G"
                }},
    "tempy":
        {
            "provider": "tmpfs",
            "attrs":
                {
                    "size": "1G"
                }},
    "ebsy":
        {
            "provider": "ebs",
            "attrs":
                {
                    "size": "1G"
                }}
}

storage_pool_1X = copy.deepcopy(storage_pool_details)
storage_pool_1X["ebs-ssd"] = {
    "provider": "ebs",
    "attrs":
        {
            "volume-type": "ssd"
        }
}

storage_list_expected = {
    "storage":
        {"data/0":
            {
                "kind": "filesystem",
                "attachments":
                    {
                        "units":
                            {
                                "dummy-storage-fs/0":
                                    {"location": "/srv/data"}}}}}}

storage_list_expected_2 = copy.deepcopy(storage_list_expected)
storage_list_expected_2["storage"]["disks/1"] = {
    "kind": "block",
    "attachments":
        {
            "units":
                {"dummy-storage-lp/0":
                    {
                        "location": ""}}}}
storage_list_expected_3 = copy.deepcopy(storage_list_expected_2)
storage_list_expected_3["storage"]["disks/2"] = {
    "kind": "block",
    "attachments":
        {
            "units":
                {"dummy-storage-lp/0":
                    {
                        "location": ""}}}}
storage_list_expected_4 = copy.deepcopy(storage_list_expected_3)
storage_list_expected_4["storage"]["data/3"] = {
    "kind": "filesystem",
    "attachments":
        {
            "units":
                {"dummy-storage-tp/0":
                    {
                        "location": "/srv/data"}}}}


def storage_list(client):
    """Return the storage list."""
    list_storage = json.loads(client.list_storage())
    for instance in list_storage["storage"].keys():
        try:
            list_storage["storage"][instance].pop("status")
            list_storage["storage"][instance].pop("persistent")
            attachments = list_storage["storage"][instance]["attachments"]
            unit = attachments["units"].keys()[0]
            attachments["units"][unit].pop("machine")
            if instance.startswith("disks"):
                attachments["units"][unit]["location"] = ""
        except Exception:
            pass
    return list_storage


def storage_pool_list(client):
    """Return the list of storage pool."""
    return json.loads(client.list_storage_pool())


def create_storage_charm(charm_dir, name, summary, storage):
    """Manually create a temporary charm to test with storage."""
    storage_charm = Charm(name, summary, storage=storage, series=['trusty'])
    charm_root = storage_charm.to_repo_dir(charm_dir)
    return charm_root


def assess_create_pool(client):
    """Test creating storage pool."""
    for name, pool in storage_pool_details.iteritems():
        client.create_storage_pool(name, pool["provider"],
                                   pool["attrs"]["size"])


def assess_add_storage(client, unit, storage_type, amount="1"):
    """Test adding storage instances to service.

    Only type 'disk' is able to add instances.
    """
    client.add_storage(unit, storage_type, amount)


def deploy_storage(client, charm, series, pool, amount="1G", charm_repo=None):
    """Test deploying charm with storage."""
    if pool == "loop":
        client.deploy(charm, series=series, repository=charm_repo,
                      storage="disks=" + pool + "," + amount)
    else:
        client.deploy(charm, series=series, repository=charm_repo,
                      storage="data=" + pool + "," + amount)
    client.wait_for_started()


def assess_deploy_storage(client, charm_series,
                          charm_name, provider_type, pool):
    """Set up the test for deploying charm with storage."""
    if provider_type == 'filesystem':
        storage = {
            "data": {
                "type": provider_type,
                "location": "/srv/data"
            }
        }
    elif provider_type == "block":
        storage = {
            "disks": {
                "type": provider_type,
                "multiple": {
                    "range": "0-10"
                }
            }
        }
    with temp_dir() as charm_dir:
        charm_root = create_storage_charm(charm_dir, charm_name,
                                          'Test charm for storage', storage)
        platform = 'ubuntu'
        charm = local_charm_path(charm=charm_name, juju_ver=client.version,
                                 series=charm_series,
                                 repository=os.path.dirname(charm_root),
                                 platform=platform)
        deploy_storage(client, charm, charm_series, pool, "1G", charm_dir)


def assess_storage(client, charm_series):
    """Test the storage feature."""
    assess_create_pool(client)
    pool_list = storage_pool_list(client)
    if client.version.startswith('2.'):
        if pool_list != storage_pool_details:
            raise JujuAssertionError(pool_list)
    elif client.version.startswith('1.'):
        print(json.dumps(pool_list))
        if pool_list != storage_pool_1X:
            raise JujuAssertionError(pool_list)
    assess_deploy_storage(client, charm_series,
                          'dummy-storage-fs', 'filesystem', 'rootfs')
    storage_list_derived = storage_list(client)
    if storage_list_derived != storage_list_expected:
        raise JujuAssertionError(storage_list_derived)
    assess_deploy_storage(client, charm_series,
                          'dummy-storage-lp', 'block', 'loop')
    storage_list_derived = storage_list(client)
    if storage_list_derived != storage_list_expected_2:
        raise JujuAssertionError(storage_list_derived)
    assess_add_storage(client, 'dummy-storage-lp/0', 'disks', "1")
    storage_list_derived = storage_list(client)
    if storage_list_derived != storage_list_expected_3:
        raise JujuAssertionError(storage_list_derived)
    assess_deploy_storage(client, charm_series,
                          'dummy-storage-tp', 'filesystem', 'tmpfs')
    storage_list_derived = storage_list(client)
    if storage_list_derived != storage_list_expected_4:
        raise JujuAssertionError(storage_list_derived)
    # storage with provider 'ebs' is only available under 'aws'
    # assess_deploy_storage(client, charm_series,
    #                       'dummy-storage-eb', 'filesystem', 'ebs')


def parse_args(argv):
    """Parse all arguments."""
    parser = argparse.ArgumentParser(description="Test Storage Feature")
    add_basic_testing_arguments(parser)
    parser.set_defaults(series='trusty')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    configure_logging(args.verbose)
    bs_manager = BootstrapManager.from_args(args)
    with bs_manager.booted_context(args.upload_tools):
        assess_storage(bs_manager.client, bs_manager.series)
    return 0


if __name__ == '__main__':
    sys.exit(main())
