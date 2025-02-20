#!/bin/bash

# This script is used to start the client
curl -s -X POST -H "Content-Type: application/json" -d '{"query": "YOLOv3", "project_name": "mmdetection"}' http://101.6.68.78:60717/retrieve_instances

#curl -s -X POST -H "Content-Type: application/json" -d '{"query": "RTMDet", "project_name": null}' http://101.6.68.78:60717/retrieve_instances
