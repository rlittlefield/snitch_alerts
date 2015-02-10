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
import subprocess
from collections import deque

import copy

from twisted.web.server import Site
from twisted.web.resource import Resource
from twisted.internet import reactor, defer
from twisted.internet import task
from twisted.web.static import File
from twisted.internet import protocol
from twisted.web.util import Redirect;
from twisted.web import server

from autobahn.twisted.websocket import WebSocketServerProtocol, WebSocketServerFactory

alert_url = 'https://api.pushbullet.com/v2/pushes';


global_buffer = deque()
global_sockets = set()

input_buffer = deque()


if getattr(sys, 'frozen', False):
    print "Loading as frozen executable"
    root_path = os.path.abspath(sys.executable)
    abspath = root_path
    print sys._MEIPASS
    if sys._MEIPASS:
        abspath = sys._MEIPASS
        os.chdir(abspath)
        root_dir = os.path.dirname(root_path)
    else:
        dname = os.path.dirname(abspath)
        os.chdir(dname)
        root_dir = dname
elif __file__:
    print "Loading as python script"
    abspath = os.path.abspath(__file__)
    dname = os.path.dirname(abspath)
    root_dir = dname
    os.chdir(dname)

class Thing(Resource):
    isLeaf = True
    started = False
    loop = None
    settings_file_path = 'settings.json'
    
    def __init__(self):
        self.client_process = None
        self.client_buffer = deque()
        self.settings = {
            'log_location': '',
            'csv_location': '',
            'alert_token': '',
            'alert_channel': '',
            'players_url': '',
            'regex': r'.+ \* (.+?) .+? snitch at (.+) \[(.+)]',
            'aux_regex' : r'alert',
            'client_location': '',
            'client_username': '',
            'client_password': '',
            'client_server': '',
            'client_groupchat': ''
        }
        try:
            with open(os.path.join(root_dir, self.settings_file_path), 'r') as settings_file:
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
        args = copy.deepcopy(request.args)
        reactor.callLater(1, self.start, args)
        request.redirect("/console.html")
        request.finish()
        return server.NOT_DONE_YET
    def start(self, args):
        for key in self.settings.keys():
            self.settings[key] = args[key][0]
            
        self.settings_file = open(os.path.join(root_dir, self.settings_file_path), 'w')
        json.dump(self.settings, self.settings_file)
        self.settings_file.close()

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
        
        if 'client_submit' in args:
            print 'starting client...'
            self.client_protocol = MinecraftClientExeProtocol(self.settings['client_groupchat'])
            reactor.spawnProcess(
                self.client_protocol,
                self.settings['client_location'],
                args = [
                    self.settings['client_location'],
                    self.settings['client_username'],
                    self.settings['client_password'],
                    self.settings['client_server'],
                    'BasicIO'
                ]
            )
            print "client is started"
            if not self.loop:
                self.loop = task.LoopingCall(self.client_tick)
                self.loop.start(1.0)
        else:
            self.file_ = open(self.settings['log_location'])
            print "Opened log file, scanning..."
            # Go to the end of file
            self.file_.seek(0,2)
            if not self.loop:
                self.loop = task.LoopingCall(self.tick)
                self.loop.start(1.0)
    def handle_line(self, line):
        matches = self.snitch_regex.findall(line)
        line = line.decode('utf8', 'ignore')
        for socket in global_sockets:
            socket.sendMessage(json.dumps({'type':'message', 'data':line}))
        
        if len(matches) > 0:
            print "[snitch]\t" + line
            self.record_snitch(*matches[0])
        else:
            print "[received]\t" + line
        return
    def client_tick(self):
        for line in self.client_protocol.lines:
            self.handle_line(line)
        self.client_protocol.lines.clear()
        for i in input_buffer:
            self.client_protocol.transport.write(i.encode('utf-8') + '\n')
        input_buffer.clear()
        return
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
            self.handle_line(line)
            self.tick() # when lines are available, process them as fast as possible
        return
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

class MinecraftClientExeProtocol(protocol.ProcessProtocol):
    def __init__(self, chat_name):
        self.buffer = deque()
        self.lines = deque()
        self.loop = None
        self.chat_name = chat_name
    def outReceived(self, data):
        data = re.sub('\xa7.', '', data)
        lines = data.split('\n')
        for line in lines:
            self.buffer.append(line)
            final_line = ''.join(self.buffer)
            self.lines.append(final_line)
            global_buffer.append(final_line)
            if len(global_buffer) > 50:
                global_buffer.popleft()
            self.buffer.clear()
    def tick(self):
        self.transport.write("sup bro\n")
    def groupchat(self):
        self.transport.write("/groupchat " + self.chat_name + "\n")
    def startLoop(self):
        self.loop = task.LoopingCall(self.tick)
        self.loop.start(50.0)
    def connectionMade(self):
        reactor.callLater(1, self.groupchat);
        reactor.callLater(10, self.startLoop);
        

class MyServerProtocol(WebSocketServerProtocol):
    def onConnect(self, request):
        print("Client connecting: {0}".format(request.peer))

    def onOpen(self):
        print("WebSocket connection open.")
        global_sockets.add(self)
        print("Finished opening")
    def onMessage(self, payload, isBinary):
        if isBinary:
            print("Binary message received: {0} bytes".format(len(payload)))
        else:
            print("Text message received: {0}".format(payload.decode('utf8')))
            # dispatch message into the stdout of the MinecraftClientExeProtocol object
            try:
                data = json.loads(payload.decode('utf8'))
            except Exception as e:
                print("Error receiving input from socket")
                return
            if data and 'data' in data:
                input_buffer.append(data['data'])
        # echo back message verbatim
        self.sendMessage(payload, isBinary)
    def onClose(self, wasClean, code, reason):
        print("WebSocket connection closed: {0}".format(reason))
        global_sockets.remove(self)
        
    
factory = WebSocketServerFactory("ws://localhost:8081", debug = True)
factory.protocol = MyServerProtocol
reactor.listenTCP(8081, factory)




def openBrowserConfig():
    webbrowser.open('http://127.0.0.1:8080')
    

    
reactor.callLater(1, openBrowserConfig);
reactor.run()

sys.exit()



