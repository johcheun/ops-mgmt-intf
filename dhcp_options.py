#!/usr/bin/env python
# (c) Copyright [2015] Hewlett Packard Enterprise Development LP
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
import sys
import urllib2
import httplib
import cookielib
from time import sleep

import ovs.dirs
import ovs.db.idl
from ovs.db import error
from ovs.db import types
import ovs.vlog

# ovs definitions
idl = None
DEF_DB = 'unix:/var/run/openvswitch/db.sock'
OVS_SCHEMA = '/usr/share/openvswitch/vswitch.ovsschema'

SYSTEM_TABLE = "System"
MGMT_INTF_NULL_VAL = 'null'
MGMT_INTF_KEY_DHCP_HOSTNAME = "dhcp_hostname"
MGMT_INTF_KEY_DHCP_DOMAIN_NAME = "dhcp_domain_name"
MGMT_INTF_KEY_DNS1 = "dns_server_1"
MGMT_INTF_KEY_DNS2 = "dns_server_2"
DEFAULT_IPV4 = '0.0.0.0'
DNS_FILE = "/etc/resolv.conf"

#Logging.
vlog = ovs.vlog.Vlog("mgmtintfcfg")

#------------------ wait_for_config_complete() ----------------


def wait_for_config_complete(idl):

    system_is_configured = 0
    while True:
        idl.run()
        for ovs_rec in idl.tables[SYSTEM_TABLE].rows.itervalues():
            if ovs_rec.cur_cfg is not None and ovs_rec.cur_cfg != 0:
                system_is_configured = ovs_rec.cur_cfg
                break

        if system_is_configured != 0:
            break
        poller = ovs.poller.Poller()
        idl.wait(poller)
        poller.block()


#  Function to empty the DNS's resolve.conf file.
#  This is to avoid the system from using any default DNS server addresses
#  that are generated by DNS daemon.
def mgmt_intf_clear_dns_conf():

    newdata = ""

    try:
        fd = open(DNS_FILE, 'w')
        fd.write(newdata)
        fd.close()
    except IOError:
        vlog.err("File operation failed for file " + DNS_FILE)

    return True


# Function to update dhcp client parameter into ovsdb
def update_mgmt_intf_status(hostname, dns_1, dns_2, domainname):
    global idl

    status_data = {}
    is_update = False

    for ovs_rec in idl.tables[SYSTEM_TABLE].rows.itervalues():
        if ovs_rec.mgmt_intf_status:
            status_data = ovs_rec.mgmt_intf_status
            break

    dhcp_hostname = status_data.get(MGMT_INTF_KEY_DHCP_HOSTNAME,
                                    MGMT_INTF_NULL_VAL)
    ovsdb_dns1 = status_data.get(MGMT_INTF_KEY_DNS1, DEFAULT_IPV4)
    ovsdb_dns2 = status_data.get(MGMT_INTF_KEY_DNS2, DEFAULT_IPV4)
    dhcp_domainname = status_data.get(MGMT_INTF_KEY_DHCP_DOMAIN_NAME,
                                      MGMT_INTF_NULL_VAL)
    if dhcp_hostname != hostname:
        if hostname != MGMT_INTF_NULL_VAL:
            status_data[MGMT_INTF_KEY_DHCP_HOSTNAME] = hostname
        else:
            del status_data[MGMT_INTF_KEY_DHCP_HOSTNAME]
        is_update = True
    if domainname != dhcp_domainname:
        if domainname != MGMT_INTF_NULL_VAL:
            status_data[MGMT_INTF_KEY_DHCP_DOMAIN_NAME] = domainname
        else:
            del status_data[MGMT_INTF_KEY_DHCP_DOMAIN_NAME]
        is_update = True

    if dns_1 != 'None':
        if dns_1 != ovsdb_dns1:
            status_data[MGMT_INTF_KEY_DNS1] = dns_1
            is_update = True
    elif ovsdb_dns1 != DEFAULT_IPV4:
        mgmt_intf_clear_dns_conf()
        del status_data[MGMT_INTF_KEY_DNS1]
        is_update = True

    if dns_2 != 'None':
        if dns_2 != ovsdb_dns2:
            status_data[MGMT_INTF_KEY_DNS2] = dns_2
            is_update = True
    elif ovsdb_dns2 != DEFAULT_IPV4:
        del status_data[MGMT_INTF_KEY_DNS2]
        is_update = True

    # create the transaction
    if is_update:
        txn = ovs.db.idl.Transaction(idl)
        setattr(ovs_rec, "mgmt_intf_status", status_data)
        status = txn.commit_block()

        if status != "success" and status != "unchanged":
            vlog.err("Updating DHCP hostname status column failed \
                        with status %s" % (status))
            return False

    return True


    ###############################  main  ###########################
def main():
    global idl
    argv = sys.argv
    n_args = 2
    dns_1 = ''
    dns_2 = ''
    domainname = ''

    if argv[1] != 'None':
        hostname = argv[1]
    else:
        hostname = MGMT_INTF_NULL_VAL

    dns_1 = argv[2]
    dns_2 = argv[3]
    if argv[4] != 'None':
        domainname = argv[4]
    else:
        domainname = MGMT_INTF_NULL_VAL

    # Locate default config if it exists
    schema_helper = ovs.db.idl.SchemaHelper(location=OVS_SCHEMA)
    schema_helper.register_columns(SYSTEM_TABLE, ["cur_cfg"])
    schema_helper.register_columns(SYSTEM_TABLE, ["mgmt_intf_status"])

    idl = ovs.db.idl.Idl(DEF_DB, schema_helper)

    seqno = idl.change_seqno    # Sequence number when we last processed the db

    # Wait until the ovsdb sync up.
    while (seqno == idl.change_seqno):
        idl.run()
        if seqno == idl.change_seqno:
            poller = ovs.poller.Poller()
            idl.wait(poller)
            poller.block()

    wait_for_config_complete(idl)

    update_mgmt_intf_status(hostname, dns_1, dns_2, domainname)

    idl.close()

if __name__ == '__main__':
    try:
        main()
    except error.Error, e:
        vlog.err("Error: \"%s\" \n" % e)
