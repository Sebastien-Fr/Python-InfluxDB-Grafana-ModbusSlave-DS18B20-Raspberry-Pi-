# -*- coding: utf-8 -*-
import os
import glob
import argparse
import sys
from influxdb import InfluxDBClient
from pymodbus.client.sync import ModbusTcpClient as ModbusClient
import logging
import struct
import ctypes
import logging
from logging.handlers import RotatingFileHandler
import time
import datetime
from datetime import timedelta
from datetime import date

os.system('modprobe w1-gpio')
os.system('modprobe w1-therm')

#*******************logger**********************
logger = logging.getLogger('chaudiere')
logger.setLevel(logging.DEBUG)
fh= RotatingFileHandler('chaudiere.log',maxBytes=1000000, backupCount=5)
fh.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
fh.setFormatter(formatter)
logger.addHandler(fh)

# add more sensor variables here based on your setup

temp=['sensor code','tttttttttt','ddddddddddd']
base_dir = '/sys/bus/w1/devices/'

device_folders = glob.glob(base_dir + '28*')

snum=3 #Number of connected temperature sensors
# Set required InfluxDB parameters.
# (this could be added to the program args instead of beeing hard coded...)
host = "localhost" #Could also use local ip address like "192.168.1.136"
port = 8086
user = "XX"
password = "XXXXX"
 
# Sample period (s).
# How frequently we will write sensor data from the temperature sensors to the database.
sampling_period = 5

def read_modbus(adressIp,register,lenght):
    try :
        client = ModbusClient(adressIp)
        rr = client.read_holding_registers(register,lenght,unit=0x01)
        values=rr.registers[0:lenght]
        client.close()
        return values
        
    except:
        logger.info ('read modbus fail:')
        logger.info(adressIp)
        values=[0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]
        return values[0:lenght]
    
def read_temp_raw(device_file): 
    f = open(device_file, 'r')
    lines = f.readlines()
    f.close()
    return lines
 
def read_temp(device_file): # checks the temp recieved for errors
    lines = read_temp_raw(device_file)
    if lines != []:
        if lines[0] != "":
            while lines[0].strip()[-3:] != 'YES':
                time.sleep(0.2)
                lines = read_temp_raw(device_file)

            equals_pos = lines[1].find('t=')
            if equals_pos != -1:
                temp_string = lines[1][equals_pos+2:]
                # set proper decimal place for C
                temp = float(temp_string) / 1000.0
                # Round temp to 2 decimal points
                temp = round(temp, 1)
            return temp
        
    else:
            logger.info ('ds18b20 fail:')
            logger.info (device_file)
            get_data_points()
          
      # value of temp might be unknown here if equals_pos == -1
    

def get_args():
    '''This function parses and returns arguments passed in'''
    # Assign description to the help doc
    parser = argparse.ArgumentParser(description='Program writes measurements data from the connected DS18B20 to specified influx db.')
    # Add arguments
    parser.add_argument(
        '-db','--database', type=str, help='Database name', required=True)
    parser.add_argument(
        '-sn','--session', type=str, help='Session', required=True)
    now = datetime.datetime.now()
    parser.add_argument(
        '-rn','--run', type=str, help='Run number', required=False,default=now.strftime("%Y%m%d%H%M"))
    
    # Array of all arguments passed to script
    args=parser.parse_args()
    # Assign args to variables
    dbname=args.database
    runNo=args.run
    session=args.session
    return dbname, session,runNo

# Two register (32 bit) based types


class x2u16Struct(ctypes.Structure):
    _fields_ = [("h", ctypes.c_uint16),
                ("l", ctypes.c_uint16)]

class convert2(ctypes.Union):
    _fields_ = [("float", ctypes.c_float),
                ("u16", x2u16Struct),
                ("sint32", ctypes.c_int32),
                ("uint32", ctypes.c_uint32)]
    

    
def get_data_points():
    PiPiscine=[0,0,0]
    Fronius=[0,0,0]
    
    #get temp piscine temp ext conso 
    values=read_modbus ('192.168.1.87',10,13)
    #print( values[0:13])
    PiPiscine[0]=values[3]
    PiPiscine[1]=values[10]/100
    PiPiscine[2]=values[12]/10

    #get production solaire
    values2=read_modbus ('192.168.0.104',500,2)
    Fronius[0]=values2[1]
    Fronius[1]=values2[0]
    #to words single dword signed
    Translate=convert2()
    Translate.u16.h = Fronius[1]
    Translate.u16.l = Fronius[0]
    Fronius[2]=Translate.sint32
    #print (Fronius[2])
    
    # Get the three measurement values from the DS18B20 sensors
    for sensors in range (snum): # change number of sensors based on your setup
        device_file=device_folders[sensors]+ '/w1_slave'
        temp[sensors] = read_temp(device_file)
        #print (device_file,sensors,temp[sensors])
    # Get a local timestamp
    timestamp=datetime.datetime.utcnow().isoformat()
    
    # Create Influxdb datapoints (using lineprotocol as of Influxdb >1.1)
    datapoints = [
        {
            "measurement": session,
            "tags": {"runNum": runNo,},
            "time": timestamp,
            "fields": {"temperature 1":temp[0],"temperature 2":temp[1],"temperature 3":temp[2],"conso":PiPiscine[0],
                       "temperature piscine":PiPiscine[1],"temperature Ext":PiPiscine[2],"Production solaire":Fronius[2]}
        }
        ]
    return datapoints

# Match return values from get_arguments()
# and assign to their respective variables


#dbname, session, runNo =get_args()
dbname="temp_logger"
session="test1"
runNo="0"
print ("Session: ", session)
print ("Run No: ", runNo)
print ("DB name: ", dbname)

# Initialize the Influxdb client
client = InfluxDBClient(host, port, user, password, dbname)
        
try:
     while True:
        # Write datapoints to InfluxDB
        datapoints=get_data_points()
        bResult=client.write_points(datapoints)
        #print("Write points {0} Bresult:{1}".format(datapoints,bResult))
            
        # Wait for next sample
        time.sleep(sampling_period)
        
        # Run until keyboard ctrl-c
except KeyboardInterrupt:
    print ("Program stopped by keyboard interrupt [CTRL_C] by user. ")
    logger.info('ctrl c')
