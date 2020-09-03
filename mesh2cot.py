#!/usr/bin/python3

# MESHTASTIC to Cursor-on-target (CoT) converter
#
# Uses https://github.com/meshtastic/Meshtastic-python
#
# Copyright (c) 2020 by Alec Murphy, MIT licensed
#   https://gitlab.com/almurphy
#

from meshtastic import StreamInterface
from pubsub import pub
import logging
import sys
import os

from time import time, gmtime, strftime, mktime
import xml.etree.ElementTree as ET
import socket

# COT destination - default to TAK multicast network
ATAK_HOST = os.getenv('ATAK_HOST', '239.2.3.1')
ATAK_PORT = int(os.getenv('ATAK_PORT', '6969'))

# Enable debug output
DEBUG_LEVEL = int(os.getenv('DEBUG', '0'))

UNIT_TYPE = os.getenv('UNIT_TYPE', 'a-f-G-U-C')
UNIT_TEAM = os.getenv('UNIT_TEAM', 'Green')
UNIT_ROLE = os.getenv('UNIT_ROLE', 'Team Member')
REMARK = ''

# Validity period of CoT events, for setting "stale" attribute
POINT_EVT_TTL = 120  # seconds

ISO_FORMAT = '%Y-%m-%dT%H:%M:%SZ'
TIME_FORMAT = '%Y-%m-%dT%H:%M:%S.000Z'

# We want the CoT UIDs to be fairly collision-proof yet deterministic
#   (same node ID same UID across all systems)
# We use a fixed 10-byte part (root) and vary the last 6-bytes (node)
UUID_ROOT = '7ea452c5-a1ec-571c-a7ac'


def makeCoT(callsign, uuid, lat, lon, alt, batt=False):
    """
    Generate a CoT XML object
    """

    # Event "how" (how the coordinates were generated)
    EV_HOW = 'm-g'  # GPS

    # Event fields
    event_attr = {
        'version': '2.0',
        'uid': uuid,
        'time': strftime(TIME_FORMAT, gmtime()),
        'start': strftime(TIME_FORMAT, gmtime()),
        'stale': strftime(TIME_FORMAT, gmtime(time() + POINT_EVT_TTL)),
        'type': UNIT_TYPE,
        'how': EV_HOW
    }

    # Point fields
    point_attr = {
        'lat': lat,
        'lon': lon,
        'hae': alt,
        'ce': '9999999.0',  # unspec
        'le': '9999999.0',  # unspec
    }

    contact_attr = {'callsign': callsign}

    precis_attr = {'geopointsrc': 'GPS', 'altsrc': 'GPS'}

    takv_attr = {
        'device': 'MESH2COT',
        'platform': 'ATAK',
        'version': '3.8-COMPAT',
        'os': '23',
    }

    # Mandatory schema, "event" element at top level, with
    #   sub-elements "point" and "detail"
    cot = ET.Element('event', attrib=event_attr)
    ET.SubElement(cot, 'point', attrib=point_attr)
    det = ET.SubElement(cot, 'detail')

    ET.SubElement(det, 'contact', attrib=contact_attr)
    ET.SubElement(det, 'uid', attrib={'Droid': callsign})
    ET.SubElement(det, 'remarks').text = REMARK
    ET.SubElement(det, '__group',
                  attrib={'name': UNIT_TEAM, 'role': UNIT_ROLE})

    # optional elements
    ET.SubElement(det, 'takv', attrib=takv_attr)
    if (batt):
        ET.SubElement(det, 'status', attrib={'battery': batt})
    ET.SubElement(det, 'precisionlocation', attrib=precis_attr)

    cotXML = '<?xml version="1.0" standalone="yes"?>'.encode('utf-8')
    cotXML += ET.tostring(cot)

    return(cotXML)


def onReceive(packet, interface):
    """Callback invoked when a packet arrives"""

    #print(f"Received: {packet}")
    #print("%08x -> %08x (SNR: %d)" %
    #      (packet['from'], packet['to'], packet['rxSnr']))
    #print(packet['decoded']);

    if ('position' in packet['decoded']):
        try:
            batt = packet['decoded']['position']['batteryLevel']
        except KeyError:
            batt = False

        if (packet['decoded']['position'].keys() >= {'latitude', 'longitude'}):
            # unfortunately since meshtastic altitude is MSL,
            #   and geoid height is also unavailable
            # ... we have no easy way to set the HAE tag
            # https://github.com/meshtastic/Meshtastic-device/issues/359
            CoT = makeCoT('mesh-%08x' % packet['from'],
                          UUID_ROOT + '-00%08x' % packet['from'],
                          '%f' % packet['decoded']['position']['latitude'],
                          '%f' % packet['decoded']['position']['longitude'],
                          '9999999.0',
                          # '%f' % packet['decoded']['position']['altitude'],
                          ('%d' % batt) if batt else False)

            logging.debug('CoT: ' + CoT.decode('utf-8'))

            # Send CoT message to ATAK network
            o_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            o_sock.sendto(CoT, (ATAK_HOST, ATAK_PORT))
            o_sock.close()


def onConnection(interface, topic=pub.AUTO_TOPIC):
    """Callback invoked when we connect/disconnect from a radio"""
    print(f"Connection changed: {topic.getName()}")


def onConnected(interface):
    """Callback invoked when we connect to a radio"""

    print("Connected to radio")
    print(interface.myInfo)
    print(interface.radioConfig)
    print("Nodes in mesh:")
    for n in interface.nodes.values():
        print(n)


def onNode(node):
    """Callback invoked when the node DB changes"""
    print(f"Node changed: {node}")


def main():
    # set debug level
    logging.basicConfig(level=logging.DEBUG if DEBUG_LEVEL else logging.INFO)
    logfile = sys.stderr

    """Subscribe to the topics the user probably wants to see"""
    pub.subscribe(onReceive, "meshtastic.receive")
    # pub.subscribe(onConnection, "meshtastic.connection")
    pub.subscribe(onConnected, "meshtastic.connection.established")
    pub.subscribe(onNode, "meshtastic.node")

    client = StreamInterface(None, debugOut=logfile)


if __name__ == "__main__":
    main()
