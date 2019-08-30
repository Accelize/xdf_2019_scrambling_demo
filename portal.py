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

import requests
import json
import argparse

class WSListFunction(object):
    """
    Extract of the Metering Web service Tests function in order to call the BigCorp Cleaning feature
    """
    def __init__(self, url=None, login=None, password=None, token=None):
        self.url = url
        self.login = login
        self.password = password
        self.token = token

    def _get_user_token_raw(self):
        r = requests.post(self.url + '/o/token/?grant_type=client_credentials', auth=(self.login, self.password),
                          headers={'Content-Type': 'application/json'})
        json_acceptable_string = r.content.decode("latin1").replace("'", "\"")
        try:
            text = json.loads(json_acceptable_string)
        except:
            text = json_acceptable_string

        return text, r.status_code

    def _get_user_token(self):

        text, status_code = self._get_user_token_raw()
        self.token = text['access_token']

    def _authentifed_call(self, method, url, data=None, headers={}):
        headers['Authorization'] = "Bearer " + str(self.token)
        headers['Content-Type'] = "application/json"
        r = requests.request(method, self.url + url, data=json.dumps(data), headers=headers)
        try:
            text = json.loads(r.content)
        except:
            text = r.content
        return text, r.status_code

    def clean_demo_environment(self, data):
        response, status = self._authentifed_call("POST", "/auth/metering/cleandemoenvironment/", data=data)
        return response, status


def clean_bigcorp_data(env='dev', product_lib='demos', 
    product_name='video_scrambling', cred='./cred.json'):
 
    # Need to provide an Admin login and password
    with open(cred, 'r+') as f:
        ak = json.load(f)

    #Select the right environment
    if env == 'prod':
        env=''
    url = f"https://master.{env}metering.accelize.com"

    #Init the Metering WS class
    listfunctionsadmin = WSListFunction(url, ak['client_id'], ak['client_secret'])
    listfunctionsadmin._get_user_token()

    # request the cleanup of the product in Organisation BigCorp.
    response, status = listfunctionsadmin.clean_demo_environment(
        data={"library": f"{product_lib}","name": f"{product_name}"})
    
    if status != 200:
        print(f"[ERROR] Portal Clean-up Failed: Status = {status} Response=[{response}]")
    else:
        print("[Portal] Clean-up Succeed!")



if __name__ == '__main__':
    
    parser = argparse.ArgumentParser()
    parser.add_argument("-e", "--env", type=str, default='dev',
            required=False, dest="env", help="Execution Environment (dev or prod)")
    parser.add_argument("-l", "--plib", type=str, default='demos',
            required=False, dest="plib", help="Product Library (from VLN)")
    parser.add_argument("-n", "--pname", type=str, default='video_scrambling',
            required=False, dest="pname", help="Product Name (from VLN)")
    parser.add_argument("-c", "--cred", type=str, default='./cred.json',
            required=False, dest="cred", help="Path to credential file (JSON)")
    args=parser.parse_args()    
    
    clean_bigcorp_data(env=args.env, product_lib=args.plib, 
        product_name=args.pname, cred=args.cred)
    
