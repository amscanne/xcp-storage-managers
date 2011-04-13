#!/usr/bin/python
# Copyright (C) 2006-2007 XenSource Ltd.
# Copyright (C) 2008-2009 Citrix Ltd.
#
# This program is free software; you can redistribute it and/or modify 
# it under the terms of the GNU Lesser General Public License as published 
# by the Free Software Foundation; version 2.1 only.
#
# This program is distributed in the hope that it will be useful, 
# but WITHOUT ANY WARRANTY; without even the implied warranty of 
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the 
# GNU Lesser General Public License for more details.
#
# Functions to read and write SR metadata 
#
from xml.dom import minidom, Node
import struct
import util
from metadata import HDR_STRING, XML_TAG, _parseXML, MD_MAJOR, MD_MINOR, \
    retrieveXMLfromFile
import os
import sys
sys.path.insert(0,'/opt/xensource/sm/snapwatchd')
from xslib import get_min_blk_size, open_file_for_write, open_file_for_read, \
    xs_file_write, xs_file_read, close_file

SECTOR_SIZE = 512
XML_HEADER = "<?xml version=\"1.0\" ?>"
SECTOR2_STRUCT = "%ds%ds%ds" % ( len(XML_HEADER),
                                   49, # UUID
                                   30) # ALLOCATION
MAX_METADATA_LENGTH_SIZE = 10
LEN_FMT = "%" + "-%ds" % MAX_METADATA_LENGTH_SIZE
SECTOR_STRUCT = "%-512s" 
UUID_TAG = 'uuid'
ALLOCATION_TAG = 'allocation'
NAME_LABEL_TAG = 'nl'
NAME_DESCRIPTION_TAG = 'nd'
SNAPSHOT_TIME_TAG = 'snapshot_time'
METADATA_OF_POOL_TAG = 'metadata_of_pool'
VDI_TAG = 'vdi'
VDI_CLOSING_TAG = '</%s>' % VDI_TAG
OFFSET_TAG = 'offset'
VDI_SECTOR_1 = "<%s><%s>%s</%s><%s>%s</%s>" % (VDI_TAG,
                                               NAME_LABEL_TAG,
                                               '%s',
                                               NAME_LABEL_TAG,
                                               NAME_DESCRIPTION_TAG,
                                               '%s',
                                               NAME_DESCRIPTION_TAG)
MAX_VDI_NAME_LABEL_DESC_LENGTH = SECTOR_SIZE - 2*len(NAME_LABEL_TAG) - \
    2*len(NAME_DESCRIPTION_TAG) - len(VDI_TAG) - 12
VDI_DELETED_TAG = 'deleted'
VDI_GEN_INFO_TAG_LIST = [VDI_DELETED_TAG, 'uuid', 'is_a_snapshot', \
                         'snapshot_of', SNAPSHOT_TIME_TAG, 'type','vdi_type', \
                         'read_only', 'managed', METADATA_OF_POOL_TAG]
ATOMIC_UPDATE_PARAMS_AND_OFFSET = {NAME_LABEL_TAG: 2,
                                        NAME_DESCRIPTION_TAG: 3}
SR_INFO_SIZE_IN_SECTORS = 4
VDI_INFO_SIZE_IN_SECTORS = 2
HEADER_SEP = ':'
SECTOR_FMT = "%s%s%s%s%s%s%s" % (HDR_STRING,
                                   HEADER_SEP,
                                   LEN_FMT,
                                   HEADER_SEP,
                                   str(MD_MAJOR),
                                   HEADER_SEP,
                                   str(MD_MINOR)
                                   )                                   

def open_file(path, write = False):
    fd = -1
    if write:
        fd = open_file_for_write(path)
        if fd == -1:
            raise IOError("Failed to open file %s for write." % path)
    else:
        fd = open_file_for_read(path)
        if fd == -1:
            raise IOError("Failed to open file %s for read." % path)

    return fd
        
def close(fd):
    if fd != -1:
        close_file(fd)
        
def requiresUpgrade(path):
    try:
        try:
            fd = -1
            fd = open_file(path)               
            sector1 = xs_file_read(fd, 0, SECTOR_SIZE).strip()
            hdr = unpackHeader(sector1)
            mdmajor = int(hdr[2])
            mdminor = int(hdr[3])
               
            if mdmajor < MD_MAJOR:
                return True
               
            if mdmajor == MD_MAJOR and mdminor < MD_MINOR:
                return True
           
            return False
        except Exception, e:
            util.SMlog("Exception checking header version, upgrading metadata."\
                       " Error: %s" % str(e))
            return True
    finally:
        close(fd)
    
def get_min_blk_size_wrapper(fd):
    min_blk_size = get_min_blk_size(fd)
    if min_blk_size == 0:
        raise "Failed to get minimum block size for the metadata file."
    else:
        return min_blk_size

# get a range which is block aligned, contains 'offset' and allows
# length bytes to be written
def getBlockAlignedRange(block_size, offset, length):
    lower = 0
    if offset%block_size == 0:
        lower = offset
    else:
        lower = offset - offset%block_size
        
    upper = lower + block_size
    
    while upper < (lower + length):
        upper += block_size
        
    return (lower, upper)

def buildHeader(len):
    # build the header, which is the first sector    
    output = SECTOR_FMT % len    
    return output

def unpackHeader(input):    
    vals = input.split(HEADER_SEP)
    return (vals[0], vals[1], vals[2], vals[3])

def getSector(str):
    sector = SECTOR_STRUCT % str
    return sector
    
def getSectorAlignedXML(tagName, value):
    # truncate data if we breach the 512 limit
    if len("<%s>%s</%s>" % (tagName, value, tagName)) > SECTOR_SIZE:
        value = value[:SECTOR_SIZE - 2*len(tagName) - 5]
        
    return "<%s>%s</%s>" % (tagName, value, tagName)
    
def getXMLTag(tagName):
        return "<%s>%s</%s>" % (tagName, '%s', tagName)
        
def updateLengthInHeader(path, length):
    try:
        try:
            md = ''
            fd = -1
            fd = open_file(path)                
            min_block_size = get_min_blk_size_wrapper(fd)            
            md = xs_file_read(fd, 0, min_block_size)
            close(fd)
           
            updated_md = buildHeader(length)
            updated_md += md[SECTOR_SIZE:]
            fd = open_file(path, True)
            xs_file_write(fd, 0, min_block_size, updated_md, len(updated_md))
        except Exception, e:
            util.SMlog("Exception updating metadata length with length: %d." 
                       "Error: %s" % (length, str(e)))        
            raise
    finally:
        close(fd)
   
def getMetadataLength(path):
    try:
        try:
            fd = -1
            fd = open_file(path)
            sector1 = xs_file_read(fd, 0, SECTOR_SIZE)
            lenstr = sector1.split(HEADER_SEP)[1]
            len = int(lenstr.strip(' '))
            return len
        except Exception, e:
            util.SMlog("Exception getting metadata length." 
                       "Error: %s" % str(e))
            raise
    finally:
        close(fd)

# This function generates VDI info based on the passed in information
# it also takes in a parameter to determine whether both the sector
# or only one sector needs to be generated, and which one
# generateSector - can be 1 or 2, defaults to 0 and generates both sectors
def getVdiInfo(Dict, generateSector = 0):
    try:
        vdi_info = ''
        if generateSector == 1 or generateSector == 0:
            if len(Dict[NAME_LABEL_TAG]) + len(Dict[NAME_LABEL_TAG]) > \
                MAX_VDI_NAME_LABEL_DESC_LENGTH:
                if len(Dict[NAME_LABEL_TAG]) > MAX_VDI_NAME_LABEL_DESC_LENGTH/2:
                    Dict[NAME_LABEL_TAG].truncate(MAX_VDI_NAME_LABEL_DESC_LENGTH/2)
               
                if len(Dict[NAME_DESCRIPTION_TAG]) > \
                    MAX_VDI_NAME_LABEL_DESC_LENGTH/2: \
                    Dict[NAME_DESCRIPTION_TAG]. \
                    truncate(MAX_VDI_NAME_LABEL_DESC_LENGTH/2)
                   
            # Fill the open struct and write it           
            vdi_info += getSector(VDI_SECTOR_1 % (Dict[NAME_LABEL_TAG], 
                                                  Dict[NAME_DESCRIPTION_TAG]))
       
        if generateSector == 2 or generateSector == 0:
            # Fill the VDI information 
            VDI_INFO_FMT = ''
            for tag in VDI_GEN_INFO_TAG_LIST:
                VDI_INFO_FMT += getXMLTag(tag)
               
            VDI_INFO_FMT += VDI_CLOSING_TAG
            
            deleted_value = '0'
            if Dict.has_key(VDI_DELETED_TAG) and Dict[VDI_DELETED_TAG] == '1':               
                deleted_value = '1'            
               
            vdi_info += getSector(VDI_INFO_FMT % (deleted_value,
                                                Dict['uuid'],
                                                Dict['is_a_snapshot'],
                                                Dict['snapshot_of'],
                                                Dict['snapshot_time'],
                                                Dict['type'],
                                                Dict['vdi_type'],
                                                Dict['read_only'],
                                                Dict['managed'],
                                                Dict['metadata_of_pool'])
                                 )
       
        return vdi_info
   
    except Exception, e:
        util.SMlog("Exception generating vdi info: %s. Error: %s" % \
                   (Dict, str(e)))
        raise       
   
def spaceAvailableForVdis(path, count):
    try:
        created = False
        try:
            # The easiest way to do this, is to create a dummy vdi and write it
            uuid = util.gen_uuid()
            vdi_info = { 'uuid': uuid,
                        'location': "dummy location",
                        NAME_LABEL_TAG: 'dummy vdi for space check',
                        NAME_DESCRIPTION_TAG: 'dummy vdi for space check',
                        'is_a_snapshot': 0,
                        'snapshot_of': '',
                        'snapshot_time': '',                               
                        'type': 'user',
                        'vdi_type': 'vhd',
                        'read_only': 0,
                        'managed': 0,
                        'metadata_of_pool': ''
            }
   
            created = addVdi(path, vdi_info)
        except IOError, e:
            raise      
    finally:
        if created:
            # Now delete the dummy VDI created above
            deleteVdi(path, uuid)
            return
    
def generateVDIsForRange(vdi_info, lower, upper, update_map = {}, offset = 0):
    value = ''
    if not len(vdi_info.keys()) or not vdi_info.has_key(offset):
        return getVdiInfo(update_map)
        
    for vdi_offset in vdi_info.keys():
        if vdi_offset < lower:
            continue
                
        if len(value) >= (upper - lower):
            break
        
        vdi_map = vdi_info[vdi_offset]                
        if vdi_offset == offset:
            # write passed in VDI info                    
            for key in update_map.keys():
                vdi_map[key] = update_map[key]
                    
        for i in range(1,3):
            if len(value) < (upper - lower):
                value += getVdiInfo(vdi_map, i)
                
    return value
                        
# generates metadata info to write taking the following parameters:
# a range, lower - upper
# sr and vdi information
# VDI information to update
# an optional offset to the VDI to update
def getMetadataToWrite(sr_info, vdi_info, lower, upper, update_map, offset):
    util.SMlog("Entering getMetadataToWrite")
    try:
        value = ''
        vdi_map = {}
        
        # if lower is less than SR info
        if lower < SECTOR_SIZE * SR_INFO_SIZE_IN_SECTORS:
            # generate SR info
            for i in range(lower/SECTOR_SIZE, SR_INFO_SIZE_IN_SECTORS):
                value += getSRInfoForSectors(sr_info, range(i, i + 1))
            
            # generate the rest of the VDIs till upper
            value += generateVDIsForRange(vdi_info, \
               SECTOR_SIZE * SR_INFO_SIZE_IN_SECTORS, upper, update_map, offset)
        else:
            # skip till you get a VDI with lower as the offset, then generate
            value += generateVDIsForRange(vdi_info, lower, upper, \
                                          update_map, offset)
        return value
    except Exception, e:
        util.SMlog("Exception generating metadata to write with info: "\
                   "sr_info: %s, vdi_info: %s, lower: %d, upper: %d, "\
                   "update_map: %s, offset: %d. Error: %s" % \
                   (sr_info, vdi_info, lower, upper, update_map, offset,str(e)))
        raise
   
def addVdi(path, Dict):
    util.SMlog("Entering addVdi")
    try:
        try:
            value = ''
            Dict[VDI_DELETED_TAG] = '0'
            
            fd = -1
            fd = open_file(path, True)
            min_block_size = get_min_blk_size_wrapper(fd)
            mdlength = getMetadataLength(path)
            md = getMetadata(path, {'firstDeleted': 1, 'includeDeletedVdis': 1})
            
            if not md.has_key('foundDeleted'):
                md['offset'] = mdlength
                (md['lower'], md['upper']) = \
                    getBlockAlignedRange(min_block_size, mdlength, \
                                        SECTOR_SIZE * VDI_INFO_SIZE_IN_SECTORS)
            # If this has created a new VDI, update metadata length 
            if md.has_key('foundDeleted'):
                value = getMetadataToWrite(md['sr_info'], md['vdi_info'], \
                        md['lower'], md['upper'], Dict, md['offset'])    
            else:
                value = getMetadataToWrite(md['sr_info'], md['vdi_info'], \
                        md['lower'], md['upper'], Dict, mdlength)    
            
            xs_file_write(fd, md['lower'], min_block_size, value, len(value))
            
            if md.has_key('foundDeleted'):
                updateLengthInHeader(path, mdlength)     
            else:
                updateLengthInHeader(path, mdlength + \
                        SECTOR_SIZE * VDI_INFO_SIZE_IN_SECTORS)
            return True
        except Exception, e:
            util.SMlog("Exception adding vdi with info: %s. Error: %s" % \
                       (Dict, str(e)))
            raise
    finally:
        close(fd)
       
def getSRInfoForSectors(sr_info, range):   
    srinfo = ''
    
    try:
        # Fill up the first sector 
        if 0 in range:           
            srinfo = getSector(buildHeader(SECTOR_SIZE))
           
        if 1 in range:
            uuid = getXMLTag(UUID_TAG) % sr_info['uuid']
            allocation = getXMLTag(ALLOCATION_TAG) % sr_info['allocation']
            second = struct.pack(SECTOR2_STRUCT,
                            XML_HEADER,
                            uuid,
                            allocation
                            )
                            
            srinfo += getSector(second)
       
        if 2 in range:
            # Fill up the SR name_label
            srinfo += getSector(getSectorAlignedXML(NAME_LABEL_TAG, 
                                              sr_info[NAME_LABEL_TAG]))
           
        if 3 in range:
            # Fill the name_description
            srinfo += getSector(getSectorAlignedXML(NAME_DESCRIPTION_TAG, 
                                              sr_info[NAME_DESCRIPTION_TAG]))
        
        return srinfo
    
    except Exception, e:
        util.SMlog("Exception getting SR info with parameters: sr_info: %s," \
                   "range: %s. Error: %s" % (sr_info, range, str(e)))
        raise
   
# This should be called only in the cases where we are initially writing
# metadata, the function would expect a dictionary which had all information
# about the SRs and all its VDIs
def writeMetadata(path, sr_info, vdi_info):
    try:
        try:
            md = ''
            fd = -1           
            md = getSRInfoForSectors(sr_info, range(0, SR_INFO_SIZE_IN_SECTORS))
           
            # Go over the VDIs passed and for each
            for key in vdi_info.keys():           
                md += getVdiInfo(vdi_info[key])          
           
            # Now write the metadata on disk.           
            fd = open_file(path, True)        
            min_block_size = get_min_blk_size_wrapper(fd)       
            xs_file_write(fd, 0, min_block_size, md, len(md))
            updateLengthInHeader(path, len(md))
           
        except Exception, e:
            util.SMlog("Exception writing metadata with info: %s, %s. "\
                       "Error: %s" % (sr_info, vdi_info, str(e)))
            raise
    finally:
        close(fd)
   
# Get metadata from the file name passed in
# additional params:
# includeDeletedVdis - include deleted VDIs in the returned metadata
# vdi_uuid - only fetch metadata till a particular VDI
# offset - only fetch metadata till a particular offset
# firstDeleted - get the first deleted VDI
# the return value of this function is a dictionary having the following keys
# sr_info: dictionary containing sr information
# vdi_info: dictionary containing vdi information indexed by offset
# offset: when passing in vdi_uuid/firstDeleted below
# deleted - true if deleted VDI found to be replaced
def getMetadata(path, params = {}):
    try:
        try:
            fd = -1
            fd = open_file(path)
            lower = 0; upper = 0
            retmap = {}; sr_info_map = {}; vdi_info_by_offset = {}
            length = getMetadataLength(path)
            min_blk_size = get_min_blk_size_wrapper(fd)
           
            # Read in the metadata fil
            metadata = ''           
            metadata = xs_file_read(fd, 0, length)
           
            # At this point we have the complete metadata in metadata
            offset = SECTOR_SIZE + len(XML_HEADER)
            sr_info = metadata[offset: SECTOR_SIZE * 4]
            offset = SECTOR_SIZE * 4
            sr_info = sr_info.replace('\x00','')
           
            parsable_metadata = '%s<%s>%s</%s>' % (XML_HEADER, XML_TAG, 
                                                   sr_info, XML_TAG)
           
            retmap['sr_info'] = _parseXML(parsable_metadata)
            
            # At this point we check if an offset has been passed in
            if params.has_key('offset'):
                upper = getBlockAlignedRange(min_blk_size, params['offset'], \
                                             0)[1]
            else:
                upper = length
            
            # Now look at the VDI objects            
            while offset < upper:                
                vdi_info = metadata[offset: 
                                offset + 
                                (SECTOR_SIZE * VDI_INFO_SIZE_IN_SECTORS)]                
                vdi_info = vdi_info.replace('\x00','')
                parsable_metadata = '%s<%s>%s</%s>' % (XML_HEADER, XML_TAG, 
                                               vdi_info, XML_TAG)                
                vdi_info_map = _parseXML(parsable_metadata)[VDI_TAG]
                vdi_info_map[OFFSET_TAG] = offset
                
                if not params.has_key('includeDeletedVdis') and \
                    vdi_info_map[VDI_DELETED_TAG] == '1':
                    offset += SECTOR_SIZE * VDI_INFO_SIZE_IN_SECTORS
                    continue
                
                vdi_info_by_offset[offset] = vdi_info_map
                if params.has_key('vdi_uuid'):
                    if vdi_info_map[UUID_TAG] == params['vdi_uuid']:
                        retmap['offset'] = offset
                        (lower, upper) = \
                            getBlockAlignedRange(min_blk_size, offset, \
                                        SECTOR_SIZE * VDI_INFO_SIZE_IN_SECTORS)
                    
                elif params.has_key('firstDeleted'):
                    if vdi_info_map[VDI_DELETED_TAG] == '1':
                        retmap['foundDeleted'] = 1
                        retmap['offset'] = offset
                        (lower, upper) = \
                            getBlockAlignedRange(min_blk_size, offset, \
                                        SECTOR_SIZE * VDI_INFO_SIZE_IN_SECTORS)
                            
                offset += SECTOR_SIZE * VDI_INFO_SIZE_IN_SECTORS
                
            retmap['lower'] = lower
            retmap['upper'] = upper                        
            retmap['vdi_info'] = vdi_info_by_offset
            return retmap           
        except Exception, e:
            util.SMlog("Exception getting metadata from path %s with params" \
                    "%s. Error: %s" % (path, params, str(e)))
            raise
    finally:
        close(fd)

def deleteVdi(path, vdi_uuid, offset = 0):
    util.SMlog("Entering deleteVdi")
    try:
        mdlength = getMetadataLength(path)
        md = getMetadata(path, {'vdi_uuid': vdi_uuid})
        if not md.has_key('offset'):
            util.SMlog("Failed to find VDI %s in the metadata, ignoring " \
                       "delete from metadata." % vdi_uuid)
            return        
        
        md['vdi_info'][md['offset']][VDI_DELETED_TAG] = '1'
        updateVdi(path, md['vdi_info'][md['offset']])
        if (mdlength - md['offset']) == VDI_INFO_SIZE_IN_SECTORS * SECTOR_SIZE:
            updateLengthInHeader(path, (mdlength - \
                                    VDI_INFO_SIZE_IN_SECTORS * SECTOR_SIZE))
    except Exception, e:
        raise Exception("VDI delete operation failed for "\
                            "parameters: %s, %s. Error: %s" % \
                            (path, vdi_uuid, str(e)))
   
# This function accepts both sr name_label and sr name_description to b
# passed in
def updateSR(path, Dict):
    util.SMlog('entering updateSR')
    
    try:
        value = ''
        fd = -1
        fd = open_file(path, True)
           
        # Find the offset depending on what we are updating
        if set(Dict.keys()) - set(ATOMIC_UPDATE_PARAMS_AND_OFFSET.keys()) == \
            set([]):
            offset = SECTOR_SIZE * 2       
            (lower, upper) = getBlockAlignedRange(get_min_blk_size_wrapper(fd),\
                                                  offset, SECTOR_SIZE * 2)
            md = getMetadata(path, \
                        {'offset': SECTOR_SIZE * (SR_INFO_SIZE_IN_SECTORS - 1)})
            
            sr_info = md['sr_info']
            vdi_info_by_offset = md['vdi_info']
           
            # update SR info with Dict
            for key in Dict.keys():
                sr_info[key] = Dict[key]
               
            # if lower is less than SR header size
            if lower < SR_INFO_SIZE_IN_SECTORS * SECTOR_SIZE:
                # if upper is less than SR header size
                if upper <= SR_INFO_SIZE_IN_SECTORS * SECTOR_SIZE:
                    for i in range(lower/SECTOR_SIZE, upper/SECTOR_SIZE):
                        value += getSRInfoForSectors(sr_info, range(i, i + 1))                      
                else:
                    for i in range(lower/SECTOR_SIZE, SR_INFO_SIZE_IN_SECTORS):
                        value += getSRInfoForSectors(sr_info, range(i, i + 1))
                   
                    # generate the remaining VDI
                    value += generateVDIsForRange(vdi_info_by_offset, 
                                SR_INFO_SIZE_IN_SECTORS, upper)
            else:
                # generate the remaining VDI
                value += generateVDIsForRange(vdi_info_by_offset, lower, upper)
            
            xs_file_write(fd, lower, get_min_blk_size_wrapper(fd), \
                          value, len(value))
        else:
            raise Exception("SR Update operation not supported for "
                            "parameters: %s" % diff)
    finally:
        close(fd)

def updateVdi(path, Dict):
    util.SMlog('entering updateVdi')
    try:
        try:
            value = ''
            fd = -1
            fd = open_file(path, True)
            min_block_size = get_min_blk_size_wrapper(fd)
            mdlength = getMetadataLength(path)
            md = getMetadata(path, {'vdi_uuid': Dict['uuid']})
            value = getMetadataToWrite(md['sr_info'], md['vdi_info'], \
                        md['lower'], md['upper'], Dict, md['offset'])
            xs_file_write(fd, md['lower'], min_block_size, value, len(value))
            return True
        except Exception, e:
            util.SMlog("Exception updating vdi with info: %s. Error: %s" % \
                       (Dict, str(e)))
            raise
    finally:
        close(fd)
