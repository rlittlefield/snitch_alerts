#!/usr/bin/python

import os
import sys
import time
import re
import requests
import json
import csv
import datetime
import StringIO
import webbrowser
from string import Template

from twisted.web.server import Site
from twisted.web.resource import Resource
from twisted.internet import reactor, defer
from twisted.internet import task
from twisted.web.static import File

alert_url = 'https://api.pushbullet.com/v2/pushes';


if getattr(sys, 'frozen', False):
    print "Loading as frozen executable"
    abspath = os.path.abspath(sys.executable)
elif __file__:
    print "Loading as python script"
    abspath = os.path.abspath(__file__)

dname = os.path.dirname(abspath)
os.chdir(dname)

class Thing(Resource):
    isLeaf = True
    started = False
    loop = None
    settings_file_path = 'settings.json'
    
    def __init__(self):
        self.log_location = ''
        self.csv_location = ''
        self.alert_token = ''
        self.alert_channel = ''
        self.players_url = ''
        self.regex = r'.+ \* (.+?) .+? snitch at (.+) \[(.+)]'
        try:
            with open(self.settings_file_path, 'r') as settings_file:
                args = json.load(settings_file)
                if args:
                    self.log_location = args['log_location']
                    self.csv_location = args['csv_location']
                    self.alert_token = args['alert_token']
                    self.alert_channel = args['alert_channel']
                    self.players_url = args['players_url']
                    self.regex = args['regex']
                print self.__dict__
        except Exception as e:
            print "no settings file found, skipping"
            print e
        Resource.__init__(self)
    def render_GET(self, request):
        output = {}
        output['log_path'] = self.log_location
        output['csv_path'] = self.csv_location 
        output['pushbullet_token'] = self.alert_token
        output['pushbullet_channel'] = self.alert_channel
        output['players_url'] = self.players_url
        output['regex'] = self.regex
        request.setHeader('Content-type', 'application/json')
        return json.dumps(output)
    def render_POST(self, request):
        print request.args
        reactor.callLater(1, self.start, request)
        return 'starting!'
    def start(self, request):
        args = request.args
        self.log_location = args['log_path'][0]
        self.csv_location = args['csv_path'][0]
        self.alert_token = args['pushbullet_token'][0]
        self.alert_channel = args['pushbullet_channel'][0]
        self.players_url = args['players_url'][0]
        self.regex = args['regex'][0]
        self.snitch_regex = re.compile(self.regex);

        
        
        self.csv_writer = None
        self.players = {}

        if (self.csv_location):
            self.csv_file = open(self.csv_location, 'ab')
            self.csv_writer = csv.writer(self.csv_file)
            
        self.fetch_players()
        print "Starting Up...";

        self.last_player_refresh = time.time()
        self.file_ = open(self.log_location)
        
        self.settings_file = open(self.settings_file_path, 'w')
        
        output_dict = {
            'log_location': self.log_location,
            'csv_location': self.csv_location,
            'alert_token': self.alert_token,
            'alert_channel': self.alert_channel,
            'players_url': self.players_url,
            'regex': self.regex,
        }
        
        json.dump(output_dict, self.settings_file)
        self.settings_file.close()
        
        print "Opened log file, scanning..."
        # Go to the end of file
        self.file_.seek(0,2)
        if not self.loop:
            self.loop = task.LoopingCall(self.tick)
            self.loop.start(1.0)
        
    def tick(self):
        if time.time() > self.last_player_refresh + 1200:
            self.fetch_players();
            self.last_player_refresh = time.time()
        self.curr_position = self.file_.tell()
        line = self.file_.readline()
        if not line:
            self.file_.seek(self.curr_position)
        else:
            line = line.replace("\r", '').replace("\n", '').strip()
            matches = self.snitch_regex.findall(line)
            if len(matches) > 0:
                print "success " + line
                self.record_snitch(*matches[0])
            else:
                print "failed " + line
            self.tick() # when lines are available, process them as fast as possible
    def record_snitch(self, player, location, coordinates):
        if self.csv_writer:
            self.csv_writer.writerow((datetime.datetime.utcnow().isoformat(), player, location, coordinates))
            self.csv_file.flush()
        ciplayer = player.lower() # in case we didn't save it correctly in the doc
        if ciplayer in self.players and self.players[ciplayer]['status'] == 'alert' and 'alerted' not in self.players[ciplayer]:
            print "ALERT ALERT ALERT ALERT"
            notice = {
                'channel_tag': 'civcarbon',
                'type': 'link',
                'body': ciplayer + ' hit snitch ' + location + ' [' + coordinates + ']\nBounty: ' + self.players[ciplayer]['bounty'] + '\nNote: ' + self.players[ciplayer]['note'],
                'url': 'https://www.reddit.com/r/Civcraft/search?q='+player+'&sort=new&restrict_sr=on'
            }
            body = json.dumps(notice)
            headers = {'Content-type': 'application/json', 'Authorization': 'Bearer ' + self.alert_token}
            r = requests.post(alert_url, auth=(self.alert_token, ''), data=body, headers=headers, verify=False)
            print r
            print str(r.text)
            self.players[ciplayer]['alerted'] = True
            
    def fetch_players(self):
        print "Fetching players..."
        self.players.clear()
        r = requests.get(self.players_url, verify=False)
        # r should now be a tsv file
        csv_read_file = StringIO.StringIO(r.text)
        csv_reader = csv.reader(csv_read_file, delimiter='\t')
        for row in csv_reader:
            player = {'status': row[1], 'note': row[2], 'bounty': row[3]}
            self.players[row[0].lower()] = player
        print "Loaded " + str(len(self.players)) + ' players'
            
        

app = Thing()

root = File('static')
root.putChild('app', app)
factory = Site(root)


reactor.listenTCP(8080, factory)

def openBrowserConfig():
    webbrowser.open('http://127.0.0.1:8080')
reactor.callLater(1, openBrowserConfig);
reactor.run()

sys.exit()



