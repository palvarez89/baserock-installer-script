#!/usr/bin/python
# Copyright (C) 2014 Codethink Limited
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 2 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.


'''A Baserock installer.'''



import morphlib
import os
import re
import sys
import json
import yaml
import subprocess
import tempfile
import errno
import time
import stat
import traceback


config_file = '/etc/install.conf'
to_mount = (
    ('/proc', 'proc', 'none'),
    ('/sys', 'sysfs', 'none'),

)

def validate_install_values(disk_dest, rootfs):
    if not is_device(disk_dest):
       print "ERROR: Not deploying to a device"
       raise BaseException
    if not os.path.exists(disk_dest):
       print "ERROR: The device %s doesn't exist." % disk_dest
       raise BaseException
    if not is_baserock_rootfs(rootfs):
       print "ERROR: The rootfs %s is not a baserock rootfs." % rootfs
       raise BaseException

def is_baserock_rootfs(rootfs):
    if os.path.isdir(os.path.join(rootfs, 'baserock')):
        return True
    return False

def compute_install_command(rawdisk_path, deployment_config,
                          rootfs, disk_dest):
    fd, script = tempfile.mkstemp()
    with os.fdopen(fd, 'w') as fp:
        fp.write('#!/bin/sh\n')
        fp.write('env ')
        for name in deployment_config:
            if deployment_config[name] is not None:
                fp.write('%s="%s" ' % (name, deployment_config[name]))
        fp.write("%s %s %s\n" % (rawdisk_path, rootfs, disk_dest))
    install_system(script)
    os.remove(script)

def finish_installation(postinstallcmd):
    os.system("sync")
    print "Executing `%s` in 5 seconds..." % postinstallcmd
    time.sleep(5)
    os.system(postinstallcmd)

def do_mounts(to_mount):
    mounted = []
    for mount_point, mount_type, source in to_mount:
        print 'Mounting %s in %s' % (source, mount_point)
        if not os.path.exists(mount_point):
            os.makedirs(mount_point)
        if mount(source, mount_point, mount_type) == 0:
            mounted.append(mount_point)
    return mounted

def mount(partition, mount_point, fstype):
    return subprocess.call(['mount', partition, mount_point, '-t', fstype])

def do_unmounts(to_unmount):
    for path in reversed(to_unmount):
        print 'Unmounting %s' % path
        try:
            subprocess.check_call(['umount', path])
        except subprocess.CalledProcessError as e:
            print 'WARNING: Failed to `umount %s`' % path

def check_and_read_config(config_file):
    print "Reading configuration from %s..." % config_file

    keys = ('INSTALLER_TARGET_STORAGE_DEVICE',
            'INSTALLER_ROOTFS_TO_INSTALL')
    try:
        with open(config_file) as f:
            config = yaml.load(f)
    except IOError as e:
        if e.errno != errno.ENOENT:
            raise
        print "WARNING: Configuration file '%s' not found" % config_file
        config = {}

    device, rootfs = (read_option(config, key)
                         for key in keys)
    postinstallcmd = read_option(config,
                        'INSTALLER_POST_INSTALL_COMMAND',
                        'reboot -f')
    return device, rootfs, postinstallcmd

def read_option(config, option, default_value=None):
    try:
        value = config[option]
    except KeyError as e:
        if default_value:
            value = default_value
        else:
            value = raw_input("Option '%s' missing, please enter a value: "
                                %   option)
    print "Option '%s' with value '%s'" % (option, value)
    return value

def get_deployment_config(rootfs):
    print "Reading deployment.meta of the system to install..."
    try:
        meta = open(os.path.join(rootfs, 'baserock/deployment.meta'))
    except IOError as e:
        if e.errno != errno.ENOENT:
            raise
        print "Failed to read deployment.meta, it will be empty"
        deployment_config = {}
    else:
        deployment_config = json.load(meta).get('configuration', {})
        meta.close()
        print "################ Environment #################"
        for key in deployment_config:
            print "# %s: %s" % (key, deployment_config[key])
        print "##############################################"
    return deployment_config


def install_system(install_script):
    subprocess.check_call(['sh', install_script])

def is_device(location):
    try:
        st = os.stat(location)
        return stat.S_ISBLK(st.st_mode)
    except OSError as e:
        if e.errno == errno.ENOENT:
            return False
        raise

    dev_regex = re.compile("^/dev/((sd|vd|mmcblk|hd)[a-z0-9]+)$")
    if dev_regex.match(location):
        return True
    return False


try:
    print "Baserock installation script begins..."
    mounted = do_mounts(to_mount)

    rawdisk_path = morphlib.extensions._get_morph_extension_filename(
                       'rawdisk', '.write')

    disk_dest, rootfs, postinstallcmd = check_and_read_config(
                                            config_file)
    validate_install_values(disk_dest, rootfs)

    deployment_config=get_deployment_config(rootfs)

    compute_install_command(rawdisk_path,
             deployment_config, rootfs, disk_dest)

    do_unmounts(mounted)
    finish_installation(postinstallcmd)
except BaseException as e:
    print traceback.format_exc()
    print "Something failed, opening shell..."
    print "Once you have finished, use `reboot -f`"
    os.execl('/bin/sh', 'sh')
