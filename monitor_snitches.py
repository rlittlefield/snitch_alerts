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
        self.settings = {
            'log_location': '',
            'csv_location': '',
            'alert_token': '',
            'alert_channel': '',
            'players_url': '',
            'regex': r'.+ \* (.+?) .+? snitch at (.+) \[(.+)]',
            'aux_regex' : r'alert'
        }
        try:
            with open(self.settings_file_path, 'r') as settings_file:
                settings = json.load(settings_file)
                for key in settings:
                    self.settings[key] = settings[key]
        except Exception as e:
            print "settings file problem"
            print e
        Resource.__init__(self)
    def render_GET(self, request):
        request.setHeader('Content-type', 'application/json')
        return json.dumps(self.settings)
    def render_POST(self, request):
        print request.args
        reactor.callLater(1, self.start, request)
        return 'starting!'
    def start(self, request):
        args = request.args
        for key in self.settings.keys():
            self.settings[key] = args[key][0]

        self.snitch_regex = re.compile(self.settings['regex'])
        self.aux_regex = re.compile(self.settings['aux_regex'])
        self.csv_writer = None
        self.players = {}

        if (self.settings['csv_location']):
            self.csv_file = open(self.settings['csv_location'], 'ab')
            self.csv_writer = csv.writer(self.csv_file)
            
        self.fetch_players()
        print "Starting Up...";

        self.last_player_refresh = time.time()
        self.file_ = open(self.settings['log_location'])
        
        self.settings_file = open(self.settings_file_path, 'w')
        
        json.dump(self.settings, self.settings_file)
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
        is_alert_player = ciplayer in self.players and self.players[ciplayer]['status'] == 'alert'
        aux_matches = self.aux_regex.search(location)
        
        if aux_matches or (is_alert_player and 'alerted' not in self.players[ciplayer]):
            print "ALERT ALERT ALERT ALERT"
            player_dict = self.players.get(ciplayer, {})
            notice = {
                'channel_tag': self.settings['alert_channel'],
                'type': 'link',
                'body': ciplayer + ' hit snitch ' + location + ' [' + coordinates + ']\nBounty: ' + player_dict.get('bounty', '') + '\nNote: ' + player_dict.get('note', 'Not in DB'),
                'url': 'https://www.reddit.com/r/Civcraft/search?q='+player+'&sort=new&restrict_sr=on'
            }
            body = json.dumps(notice)
            headers = {'Content-type': 'application/json', 'Authorization': 'Bearer ' + self.settings['alert_token']}
            r = requests.post(alert_url, auth=(self.settings['alert_token'], ''), data=body, headers=headers, verify=False)
            print r
            print str(r.text)
            if ciplayer not in self.players:
                self.players[ciplayer] = player_dict
            self.players[ciplayer]['alerted'] = True
            
    def fetch_players(self):
        print "Fetching players..."
        self.players.clear()
        r = requests.get(self.settings['players_url'], verify=False)
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



