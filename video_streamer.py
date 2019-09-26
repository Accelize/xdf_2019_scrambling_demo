#!/usr/bin/python36
#  coding=utf-8
"""
	Entry Point
	Python Modules Pre-requisites:   
		pip3 install -U streamlink ffmpeg-python numpy pyopencl xmltodict
        
  -------  MpegTS   -----  RAW bgr24  ------  RAW bgr24  ----- 
 | SLINK |-------->| DEC |---------->| FPGA |---------->| ENC |------>
  -------  (pipe)   -----    (pipe)   ------    (pipe)   -----  (UDP)
 

    ffplay -an -sn -framedrop -probesize 32 udp://127.0.0.1:8082
    ffplay -an -sn -framedrop -fflags nobuffer+fastseek+flush_packets -flags low_delay -strict experimental udp://127.0.0.1:8082          
    mpv --no-cache --no-demuxer-thread --vd-lavc-threads=1 udp://127.0.0.1:8082
"""

import sys
import os
import time
from datetime import timedelta, datetime
import argparse
import ctypes
import fpga_app
from streamlink import Streamlink
import ffmpeg
from threading import Thread

STREAMDICT = {
    "bloomberg_us":"https://www.youtube.com/watch?v=dp8PhLsUcFE",
    "skynews_uk":"https://www.youtube.com/watch?v=siyW0GOBtbo",
    "abcnews_australia":"https://www.youtube.com/watch?v=kwxtkBcayK8",
    "aljazeera_english":"https://www.youtube.com/watch?v=jL8uDJJBjMA",
    "dwnews_english":"https://www.youtube.com/watch?v=NvqKZHpKs-g",
    "france24_english":"https://www.youtube.com/watch?v=Af_7Gyfp8qI",
    "nasa_english":"https://www.youtube.com/watch?v=nA9UZF-SZoQ",
    "accelize_webinar":"https://www.youtube.com/watch?v=rcfhb184qC8"
}    
RESOLUTIONLIST= ['480p', '360p', '244p', 'worst']

FPGA_BITSTREAM_AWS='rtl_scrambler_pipes_drm_aws.awsxclbin'
FPGA_BITSTREAM_U200='rtl_scrambler_pipes_drm_u200_xdma_201830_2.xclbin'
RECORD_FILE='record.ts'
BSIZE=(1024*1024)

# define Python user-defined exceptions
class Error(Exception):
   """Base class for other exceptions"""
   pass
class UnknownFPGAboard(Error):
   """Raised when provided board name is not supported/recognized"""
   pass
class NoAvailableStream(Error):
   """Raised when no video stream was found"""
   pass  
            
    
class fpgaStream:
    """
    """
    def __init__(self, board, target_url, drmbypass=False, 
                    reset=False, verbosity=False):
        self.exit=False
        self.slink_exit=False
        self.target_url=target_url
        self.stream=None
        self.stream_fd=None
        self.stream_url=None
        self.width=None
        self.height=None
        self.frame_size=None
        self.stream_opened=False
        self.slk = Streamlink()
        self.slink_running=False
        self.fapp_xclbin=None
        self.fapp_drmbypass=drmbypass
        self.dec_process=None
        self.enc_process=None
        self.board=board
        self.board_reset=reset
        self.verb=verbosity
        if board == 'aws':
            self.fapp_xclbin=FPGA_BITSTREAM_AWS
        elif board == 'u200':
            self.fapp_xclbin=FPGA_BITSTREAM_U200
        else:
            raise UnknownFPGAboard(f'FPGA Board {board} not supported')
        self.thread_slk = Thread(target=self.slink_read)
    
    
    def __del__(self):
        if self.stream_opened:
            self.stream_fd.close()
 
 
    def slink_read(self):
        while self.slink_exit==False:
            try:
                data = self.stream_fd.read(self.frame_size)
                if len(data)==0:
                    print("[WARNING] streamlink_read: Unable to read from fd")
                else:
                    self.dec_process.stdin.write(data)
                time.sleep(1)
            except:
                pass

        
    def open_stream(self, streamUrl):
        if streamUrl is not None:
            try:
                print(f"Trying to reach Custom URL = {streamUrl}")
                streams = self.slk.streams(streamUrl)
                for res in RESOLUTIONLIST:
                    if res in streams:
                        self.stream = streams[res]        
                        self.stream_fd = self.stream.open()
                        self.get_frame_size()
                        self.stream_url=streams[res].to_url()
                        self.stream_opened=True
                        return
            except:
                pass
        
        for name, url in STREAMDICT.items():            
            try:
                print(f"Trying to reach {name} at url={url}")
                streams = self.slk.streams(url)
                for res in RESOLUTIONLIST:
                    if res in streams:
                        self.stream = streams[res]        
                        self.stream_fd = self.stream.open()
                        self.get_frame_size()
                        self.stream_url=streams[res].to_url()
                        self.stream_opened=True
                        return
            except:
                pass
        raise NoAvailableStream('Unable to find available stream')


    def get_frame_size(self):
        with open(RECORD_FILE, 'wb+') as f:
            data = self.stream_fd.read(4*1024)
            f.write(data)
        probe = ffmpeg.probe(RECORD_FILE)
        video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
        self.width  = int(video_stream['width'])
        self.height = int(video_stream['height'])
        self.frame_size = self.width*self.height*3
        print(f"ffprobe: w={self.width} h={self.height}")
        os.remove(RECORD_FILE)

        
    def aligned_array(self, alignment, dtype, n):
        mask = alignment - 1
        if alignment == 0 or alignment & mask != 0:
            raise ValueError('alignment is not a power of 2')
        size = n * ctypes.sizeof(dtype) + mask
        buf = (ctypes.c_char * size)()
        misalignment = ctypes.addressof(buf) & mask
        if misalignment:
            offset = alignment - misalignment        
        else:
            offset = 0
        return (dtype * n).from_buffer(buf, offset)
        

    def start_slink_only_process(self):
        print('Starting Streamlink Only Process...')
        self.dec_process = ffmpeg.input('pipe:', f='mpegts')
        self.dec_process = ffmpeg.output(self.dec_process.video, 
            f"udp://{self.target_url}", f='mpegts')
        self.dec_process = ffmpeg.run_async(self.dec_process, quiet=True, 
            pipe_stdin=True)        
        self.thread_slk.start()
        input()
        
        
    def print_ffmpeg_cmd(self, ffstream):
        txt=ffstream.get_args()
        cmdline=''
        for t in txt:
            cmdline+=f"{t} "
        print(cmdline)
        
        
    def start_bypass_process(self):
        while self.dec_process.poll() is None:
            try:
                raw_bytes = self.dec_process.stdout.read(self.frame_size)
                if not raw_bytes:
                    time.sleep(0.33)
                    continue
                self.enc_process.stdin.write(raw_bytes)
                
            except KeyboardInterrupt:
                print('Stopping Stream Processing...')
                break
        
        
    def start_fpga_process(self):
        in_bytes  = self.aligned_array(4096, ctypes.c_byte, self.frame_size)
        out_bytes = self.aligned_array(4096, ctypes.c_byte, self.frame_size)
           
        self.fapp = fpga_app.fpgaApp(self.fapp_xclbin, self.fapp_drmbypass, 
            data_size=self.frame_size, buffIn=in_bytes, 
            buffOut=out_bytes, board=self.board, reset=self.board_reset)
        if self.verb:
            print(self.fapp)        
        
        print('Starting Stream Processing...')
        frame_cnt=0
        start_time = time.monotonic()
        while True:
            try:
                raw_bytes = self.dec_process.stdout.read(self.frame_size)
                if not raw_bytes:
                    print("[WARNING] FPGA Process: Unable to read from pipe")
                    time.sleep(0.33)
                    continue
                
                ctypes.memmove(ctypes.addressof(in_bytes),
                       bytes(raw_bytes), len(raw_bytes))
                
                self.fapp.send()               
                self.fapp.recv()                
                self.enc_process.stdin.write(out_bytes)
                
                if self.verb:
                    now = datetime.now()
                    end_time = time.monotonic()
                    message = (
                        f"\r[{now.year}/{now.month}/{now.day} " 
                        f"{now.hour}:{now.minute}:{now.second}] "
                        f"Processing frame {frame_cnt} - Running since "
                        f"{timedelta(seconds=end_time-start_time)}"
                    )                
                    sys.stdout.write(message)
                    sys.stdout.flush()
                    frame_cnt += 1
                
            except KeyboardInterrupt:
                print('Stopping Stream Processing...')
                self.fapp.release_drm()           
                break
        
        
    def start_stream_decoder(self):
        print('Starting Stream Decoder...')
        self.dec_process = ffmpeg.input('pipe:', blocksize=BSIZE, f='mpegts')
        self.dec_process = ffmpeg.output(self.dec_process.video, 'pipe:', 
                blocksize=BSIZE, f='rawvideo', pix_fmt='bgr24')
        self.dec_process = ffmpeg.run_async(self.dec_process, quiet=True, 
            pipe_stdin=True, pipe_stdout=True)        
        self.thread_slk.start()     
     
     
    def stop_stream_decoder(self):
        print('Stopping Stream Decoder...')
        self.slink_exit=True
        #self.thread_slk.join() 
        #self.dec_process.stdout.flush()
        #self.dec_process.stdin.close() 
        #self.dec_process.stdout.close()  
        #self.dec_process.wait()
        
        
    def start_stream_encoder(self):
        print('Starting Stream Encoder...')
        self.enc_process = ffmpeg.input('pipe:', blocksize=BSIZE, f='rawvideo', pix_fmt='bgr24', 
                s=f'{self.width}x{self.height}')
        self.enc_process = ffmpeg.output(self.enc_process.video, f"udp://{self.target_url}", 
                f='mpegts', framerate=30, maxrate='1M', bufsize='1M' )
        self.enc_process = ffmpeg.overwrite_output(self.enc_process)
        self.enc_process = ffmpeg.run_async(self.enc_process, quiet=True, pipe_stdin=True)


    def stop_stream_encoder(self):
        print('Stopping Stream Encoder...')
        #self.enc_process.stdin.close()
        #self.enc_process.wait()
        

def run(board='aws', stream=None, url='52.48.128.138:8082', 
            bpdrm=False, bpfpga=False, slinkonly=False, 
            reset=False, verbose=False):
    
    if(verbose):
        os.environ['FFREPORT'] = "1"
    
    fst = fpgaStream(board=board, target_url=url, drmbypass=bpdrm, 
            reset=reset, verbosity=verbose)
    fst.open_stream(streamUrl=stream)
    
    if(slinkonly):
        fst.start_slink_only_process()
    else:
        fst.start_stream_decoder()
        fst.start_stream_encoder()
        
        if(bpfpga):
            fst.start_bypass_process()
        else:
            fst.start_fpga_process()
        
        fst.stop_stream_decoder()
        fst.stop_stream_encoder()

         
if __name__ == '__main__':    
    parser = argparse.ArgumentParser()
    parser.add_argument("-b", "--board", type=str, default='aws',
            required=False, dest="board", help="Execution FPGA Board")
    parser.add_argument("-s", "--stream", type=str, default=None,
            required=False, dest="stream", help="Stream URL")
    parser.add_argument("-u", "--url", type=str, default='52.48.128.138:8082',
            required=False, dest="url", help="Destination URL for output stream. Format is IP:PORT")
    # DEBUG MODES
    parser.add_argument("--drm-bypass", action="store_true", dest="bpdrm", 
            help="Skip DRM activation and deactivation steps")
    parser.add_argument("--fpga-bypass", action="store_true", dest="bpfpga", 
            help="Send Streamlink data to output stream directly")
    parser.add_argument("--slink-only", action="store_true", dest="slink", 
            help="Display Streamlink output")
    parser.add_argument("-r", "--reset", action="store_true", dest="rst", 
            help="Reset Board")
    parser.add_argument("-v", "--verbose", action="store_true", dest="verb", 
            help="Verbose mode")
    
    args=parser.parse_args()   
    run(board=args.board, stream=args.stream, url=args.url, 
            bpdrm=args.bpdrm, bpfpga=args.bpfpga, slinkonly=args.slink, 
            reset=args.rst, verbose=args.verb)
    
