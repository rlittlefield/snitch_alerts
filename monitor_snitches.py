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
from string import Template

from twisted.web.server import Site
from twisted.web.resource import Resource
from twisted.internet import reactor
from twisted.internet import task

alert_url = 'https://api.pushbullet.com/v2/pushes';
snitch_regex = re.compile(r'\[(.+?)] .+ \[CHAT] .*? \* (.+) entered snitch at (.+) \[(.+)]')

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
        try:
            with open(self.settings_file_path, 'r') as settings_file:
                args = json.load(settings_file)
                if args:
                    self.log_location = args['log_location']
                    self.csv_location = args['csv_location']
                    self.alert_token = args['alert_token']
                    self.alert_channel = args['alert_channel']
                    self.players_url = args['players_url']
                print self.__dict__
        except Exception as e:
            print "no settings file found, skipping"
            print e
        Resource.__init__(self)
    def render_GET(self, request):
        output = Template(u"""
<html>
    <h1>Welcome to the config page!</h1>
    
    <form action="/" method="POST">
        <p> We just need to fill out a few quick items before we can get started.</p>
        <ol>
            <li>
                <span>What is the full path to your minecraft chat log?</span>
                <input type="text" value="$log_location" name="log_path" />
            </li>
            <li>
                <span>Full path to where you want to save the snitch logs (csv)</span>
                <input type="text" value="$csv_location" name="csv_path" />
            </li>
            <li>
                <span>PushBullet API token</span>
                <input type="text" value="$alert_token" name="pushbullet_token" />
            </li>
            <li>
                <span>PushBullet Channel</span>
                <input type="text" value="$alert_channel" name="pushbullet_channel" />
            </li>
            <li>
                <span>TSV export of badguy list url (google doc export url)</span>
                <p>You need to get the export url of the public facing google doc. This can be done in several ways, but the easiest is to go to the "share" link, get a public URL, then open an icognito window and go to that URL. Then export the thing as a TSV, and go to your chrome downloads page, right click on it, and copy the URL.</p>
                <input type="text" value="$players_url" name="players_url" />
            </li>
        </ol>
        <input type="submit" value="Start!" />
    </form>
    
</html>
        """).safe_substitute(self.__dict__)
        
        return str(output)
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
            'players_url': self.players_url
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
            matches = snitch_regex.findall(line)
            if len(matches) > 0:
                print "success " + line
                self.record_snitch(*matches[0])
            else:
                print "failed " + line
            self.tick() # when lines are available, process them as fast as possible
    def record_snitch(self, timestamp, player, location, coordinates):
        if self.csv_writer:
            self.csv_writer.writerow((datetime.datetime.utcnow().isoformat(), player, location, coordinates))
            self.csv_file.flush()
        ciplayer = player.lower() # in case we didn't save it correctly in the doc
        if ciplayer in self.players and self.players[ciplayer]['status'] == 'alert' and 'alerted' not in self.players[ciplayer]:
            print "ALERT ALERT ALERT ALERT"
            notice = {
                'channel_tag': 'civcarbon',
                'type': 'note',
                'body': ciplayer + ' hit snitch ' + location + ' [' + coordinates + ']\nBounty: ' + self.players[ciplayer]['bounty'] + '\nNote: ' + self.players[ciplayer]['note']
            }
            body = json.dumps(notice)
            headers = {'Content-type': 'application/json', 'Authorization': 'Bearer ' + self.alert_token}
            r = requests.post(alert_url, auth=(self.alert_token, ''), data=body, headers=headers)
            print r
            print str(r.text)
            self.players[ciplayer]['alerted'] = True
            
    def fetch_players(self):
        print "Fetching players..."
        self.players.clear()
        r = requests.get(self.players_url)
        # r should now be a tsv file
        csv_read_file = StringIO.StringIO(r.text)
        csv_reader = csv.reader(csv_read_file, delimiter='\t')
        for row in csv_reader:
            player = {'status': row[1], 'note': row[2], 'bounty': row[3]}
            self.players[row[0].lower()] = player
        print "Loaded " + str(len(self.players)) + ' players'
            
        

root = Thing()

        
factory = Site(root)
reactor.listenTCP(8080, factory)
reactor.run()

sys.exit()



