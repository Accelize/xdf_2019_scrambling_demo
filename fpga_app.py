#!/usr/bin/env python
# -*- coding: utf-8 -*-

# pylint: disable=C0301
"""
    Accelize Getting Started Example Designs
    Python binding
    
    ********************************************************************
    * Description:   *
    ********************************************************************
"""
import sys
import os
import argparse
import time
import ctypes
import pyopencl as cl
import numpy as np
import xmltodict
import json
from threading import Thread

# Accelize DRM Library
from accelize_drm import DrmManager as _DrmManager
from accelize_drm.fpga_drivers import get_driver as _get_driver


class fpgaApp:
    def __init__(self, xclbin=None, drmbypass=False, data_size=4096, 
                    buffIn=None, buffOut=None, board=None, reset=False):
        self.xclbin=xclbin
        self.drmbypass=drmbypass
        self.drm_base_address=self.get_drmbaseaddr_from_xclbin(xclbin)
        self.data_size=data_size
        self.board=board
        self.board_reset_cmd=''
        self.ocl_ctx = None
        self.ocl_prg = None
        self.ocl_q = None
        self.ocl_krnl_scramb_stage  = None
        self.ocl_krnl_input_stage  = None
        self.ocl_krnl_output_stage = None        
        self.fpga_driver_name = None
        self.fpga_driver = None
        self.drm_manager = None
        self.drm_activated=False
        self.thread_drm_activation = None
        self.init_board(board, reset)
        self.init_hal(buffIn, buffOut)
        self.thread_drm_activation = Thread(target=self.drm_activation_thread)
        self.init_drm()
     
     
    def __del__(self):
        try:
            self.release_drm()
            self.drm_manager = None
        except:
            pass
            
    def __str__(self):
        s  = "\n"
        s += f"fpgaApp:\n"
        s += f"\tboard            = {self.board}\n"
        s += f"\tdrm_base_address = {hex(self.drm_base_address)}\n"
        s += f"\tboard_reset_cmd  = {self.board_reset_cmd}\n"
        s += f"\tfpga_driver_name = {self.fpga_driver_name}\n"
        s += f"\txclbin           = {self.xclbin}\n"
        s += f"\tdata_size        = {self.data_size}\n"
        s += f"\tdrm_activated    = {self.drm_activated}\n"
        s += "\n"
        return s
    
    
    def reset_board(self):
        print('Forcing Reset of FPGA Chip...')
        os.system(self.board_reset_cmd)
            
            
    def init_board(self, board, reset=False):
        if board=='aws':
            self.fpga_driver_name='aws_f1'           
            self.board_reset_cmd='fpga-clear-local-image -S 0 -H'
        if board=='u200':
            self.fpga_driver_name='xilinx_xrt'
            self.board_reset_cmd='xbutil reset -d 0'
        if reset:
           self.reset_board()
            
            
    def get_drmbaseaddr_from_xclbin(self, xclbin):
        pattern_start = '<project name="'
        pattern_end = '</project>'
        start=None
        end=None
        xmltxt=None
        with open(xclbin, "rb") as f:
            for line in f:
                try:
                    l = line.decode('utf-8')
                    if(pattern_start in l):
                        start = f.tell() - len(line)
                    if(pattern_end in l):
                        end = f.tell()-1
                        break
                except UnicodeDecodeError:
                    continue
        
        with open(xclbin, "r") as f:
            f.seek(start, 0)
            xmltxt = f.read(end-start)
        xmld = xmltodict.parse(xmltxt)    
        for krnl in xmld['project']['platform']['device']['core']['kernel']:
            if(krnl['@name']=='drm_controller_axi4st'):
                return int(krnl['instance']['addrRemap']['@base'], 16)
        return None
    
    
    def init_hal(self, buffIn, buffOut):
        # Get platform/device information
        clPlatform = cl.get_platforms()[0]
        clDevices = clPlatform.get_devices()
        clDevice = clDevices[0]
        
        self.ocl_ctx = cl.Context(devices=clDevices)
        
        with open(self.xclbin, "rb") as binary_file:
            binary = binary_file.read()        
        self.ocl_prg = cl.Program(self.ocl_ctx, clDevices, [binary])
        
        # Init Command Queue
        qprops = cl.command_queue_properties.OUT_OF_ORDER_EXEC_MODE_ENABLE|\
             cl.command_queue_properties.PROFILING_ENABLE
        self.ocl_q = cl.CommandQueue(context=self.ocl_ctx, device=clDevice, 
                properties=qprops)
        
        # Create Kernels
        self.ocl_krnl_scramb_stage = cl.Kernel(self.ocl_prg, "krnl_scrambler_stage_rtl")
        self.ocl_krnl_input_stage  = cl.Kernel(self.ocl_prg, "krnl_input_stage_rtl")
        self.ocl_krnl_output_stage = cl.Kernel(self.ocl_prg, "krnl_output_stage_rtl")
        
        # Create Buffers
        self.buffer_input  = cl.Buffer(self.ocl_ctx, 
                cl.mem_flags.USE_HOST_PTR|cl.mem_flags.READ_ONLY, 
                size=0, hostbuf=buffIn)
        self.buffer_output = cl.Buffer(self.ocl_ctx, 
                cl.mem_flags.USE_HOST_PTR|cl.mem_flags.WRITE_ONLY, 
                size=0, hostbuf=buffOut) 
        
        
    def send(self):
        # Set the Kernel Arguments
        npSize = np.int32(self.data_size/4)
        self.ocl_krnl_input_stage.set_args(self.buffer_input, npSize)
        
        # Copy input data to device global memory
        cl.enqueue_migrate_mem_objects(self.ocl_q, [self.buffer_input], 
            flags=0)
        
        # Launch the Kernel
        cl.enqueue_nd_range_kernel(self.ocl_q, self.ocl_krnl_input_stage, 
            [1], [1])
        
        
    def recv(self):
        # Set the Kernel Arguments
        npSize = np.int32(self.data_size/4)
        npIncr = np.int32(0)
        self.ocl_krnl_scramb_stage.set_args(npIncr, npSize)
        self.ocl_krnl_output_stage.set_args(self.buffer_output, npSize)
        
        # Launch the Kernel
        cl.enqueue_nd_range_kernel(self.ocl_q, self.ocl_krnl_scramb_stage, 
            [1], [1])
        cl.enqueue_nd_range_kernel(self.ocl_q, self.ocl_krnl_output_stage,
            [1], [1])

        self.ocl_q.finish()
        
        # Copy Result from Device Global Memory to Host Local Memory
        cl.enqueue_migrate_mem_objects(self.ocl_q, [self.buffer_output], 
            flags=cl.mem_migration_flags.HOST)
        self.ocl_q.finish()
        
        
    def init_drm(self, fpga_slot_id=0):
        if not self.drmbypass:
            
            # Get FPGA driver
            self.fpga_driver = _get_driver(name=self.fpga_driver_name)(
                fpga_slot_id=fpga_slot_id,
                #fpga_image=fpga_image,
                drm_ctrl_base_addr=self.drm_base_address)
                #log_dir=self.LOG_DIR)
            
            self.drm_manager = _DrmManager(
                conf_file_path="./conf.json",
                cred_file_path="./cred.json",
                read_register=self.fpga_driver.read_register_callback,
                write_register=self.fpga_driver.write_register_callback,
                async_error=self.async_error_callback
                #self.drm_read_callback,
                #self.drm_write_callback,
            )
            self.thread_drm_activation.start()
            time.sleep(2)
    
    
    def drm_activation_thread(self):
        while True:
            if self.drm_activated==False:
                try:
                    self.drm_manager.activate()
                    self.drm_activated=True
                    print(f"[DRMLIB] Session ID: {self.drm_manager.get('session_id')}")
                except:
                    self.drm_activated=False
            time.sleep(1)
                        
                        
    def async_error_callback(self, err_mess):
        self.drm_activated=False
        return None
        
        
    def release_drm(self):
        if not self.drmbypass:
            self.drm_manager.deactivate()

    
def run(xclbinpath=None, frame_size=None, bypassDRM=False):

    DATA_SIZE=4096
    INCR_VALUE=10
        
    source_input      = np.arange(DATA_SIZE, dtype=np.uint32)
    source_sw_results = np.arange(INCR_VALUE, DATA_SIZE + INCR_VALUE, 
                            dtype=np.uint32)
    source_hw_results = np.zeros(DATA_SIZE, np.uint32)
 
    fapp = fpgaApp(xclbinpath)
    fapp.send(source_input)
    fapp.recv(source_hw_results)
    
    fapp.release_drm()
    
    diff = source_hw_results != source_sw_results
    if diff.any():
        print(f"Error: Result mismatch")
        fapp.printDiff(source_sw_results, source_hw_results)
        raise
    print("TEST PASSED")

if __name__ == '__main__':

    # Parse the arguments
    option = argparse.ArgumentParser()
    
    option.add_argument('-x', '--xclbin', dest="xclbin_path", 
                        type=str, default=None,
                        required=True, help="Path to .xclbin file")
    
    args = option.parse_args()
    run(args.xclbin_path)
    
