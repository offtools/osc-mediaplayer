#!/bin/python

import os
import stat
import socket
import subprocess
import liblo
import pyinotify
import time
import datetime
import json
from os.path import expanduser

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gtk
from gi.repository import Gio
from gi.repository import GdkPixbuf
from gi.repository import Json

class EventHandler(pyinotify.ProcessEvent):
    def __init__(self):
        self.__current_file = None
        self.__creation_time = None
        
    def process_IN_CREATE(self, event):
        print ("Creating:", event.pathname, datetime.datetime.now())
        self.__creation_time = str(datetime.datetime.now())
        self.__current_file =  event.pathname

    def process_IN_CLOSE_WRITE(self, event):
        print ("Removing:", event.pathname)
        self.__current_file = None
        self.__creation_time = None

    def current(self):
        return self.__current_file, self.__creation_time

class Application():
    COL_NUMBER = 0
    COL_FILEPATH = 1
    
    COL_REPLAY_FILE = 0
    COL_REPLAY_IN = 1
    COL_REPLAY_OUT = 2
    COL_REPLAY_START = 3


    PLAYER_STATUS_STOPPED = 0 
    PLAYER_STATUS_PLAYING = 1
    PLAYER_STATUS_PAUSED = 2

    def __init__(self):
        handlers = {
            # actions
            "on_quit": self.on_quit,
            "on_about": self.on_about,
            "on_load": self.on_load,
            "on_save": self.on_save,
            "on_saveas": self.on_saveas,
            # start 
            "on_start_toggled": self.on_start_toggled,
            #replay
            "on_replay_in": self.on_replay_in,
            "on_replay_out": self.on_replay_out,
            "on_replay_queue": self.on_replay_queue,
            "on_replay_play": self.on_replay_play,
            "on_replay_speed_changed": self.on_replay_speed_changed,
            "on_replay_speed_reset": self.on_replay_speed_reset,
            # player
            "on_player_play": self.on_player_play,
            "on_player_pause": self.on_player_pause,
            "on_player_stop": self.on_player_stop,
            "on_player_next": self.on_player_next,
            "on_player_prev": self.on_player_prev,            
            # config
            "on_config": self.on_config,
            # config callbacks
            "on_port_changed": self.on_port_changed,
            "on_universe_changed": self.on_universe_changed,
            "on_address_changed": self.on_address_changed,
            "on_fifo_activate": self.on_fifo_activate,
            "on_playbackfolder_set": self.on_playbackfolder_set,
            "on_replayfolder_set": self.on_replayfolder_set,
            "on_extargs_activate": self.on_extargs_activate
        }

        # init gtk stuff
        builder = Gtk.Builder()
        builder.add_from_file("oscmplayer.ui")
        builder.connect_signals(handlers)

        self.window = builder.get_object("window")
        self.starttoggle =  builder.get_object("playtoggle")

        self.port = builder.get_object("adjustment_port")
        self.universe = builder.get_object("adjustment_universe")
        self.channel = builder.get_object("adjustment_channel")
        self.fifo = builder.get_object("fifo")
        self.extargs = builder.get_object("extargs")

        self.statusbar = builder.get_object("statusbar")
        self.context = self.statusbar.get_context_id("mplayer osc bridge")

        self.pb_model = builder.get_object("liststore")
        self.pb_tree = builder.get_object("treeview")
        self.pb_selection = builder.get_object("treeview-selection")
        
        self.rp_model = builder.get_object("liststore1")
        self.rp_selection = builder.get_object("treeview-selection2")
        self.rp_speed_label = builder.get_object("label13")
        self.rp_speed = builder.get_object("adjustment_rp_speed")
        self.rp_preroll = builder.get_object("adjustment_rp_preroll")

        self.configdialog =  builder.get_object("configdialog")
        self.configdialog.add_button("Close", Gtk.ResponseType.OK)
        
        home = expanduser("~")
        self.pb_folder = home
        self.filechooser_playback = builder.get_object("filechooser_playback")
        self.filechooser_playback.set_current_folder_uri('file:///%s'%(self.pb_folder))       
        self.rp_folder = home
        self.filechooser_replay = builder.get_object("filechooser_replay")
        self.filechooser_replay.set_current_folder_uri('file:///%s'%(self.rp_folder))

        menuitem = builder.get_object("menuitem_file_quit")
        menuitem.set_sensitive(True)
        menuitem = builder.get_object("menuitem_file_config")
        menuitem.set_sensitive(True)

        self.started = False

        # OBS
        self.replay_file = ""
        self.inpoint = ""
        self.outpoint = ""
        self.watch_manager = pyinotify.WatchManager()  # Watch Manager
        self.event_handler = EventHandler()
        self.notifier = pyinotify.ThreadedNotifier(self.watch_manager, self.event_handler)
        self.notifier.start()
        self.start_monitor()

        # Player
        self.proc = None
        self.mpvsock = None
        self.player_status = Application.PLAYER_STATUS_STOPPED

        # OSC ServerThread
        self.server = None

        self.filename = os.path.join(home, 'Unbenannt.json')


#####################################################################
#       GTK
#####################################################################

    def run(self):
        self.window.show_all()
        Gtk.main()
            
    def start_bridge(self):
        try:
            universe = int(self.universe.get_value())-1
            port = int(self.port.get_value())
            channel = int(self.channel.get_value())-1
            spath = self.fifo.get_text()
            extargs = self.extargs.get_text().split()
    
            self.server = liblo.ServerThread(port)
            self.server.add_method("/%i/dmx/%i"%(universe,channel), 'f', self.cb_stop)
            self.server.add_method("/%i/dmx/%i"%(universe,channel+1), 'f', self.cb_pause)
            self.server.add_method("/%i/dmx/%i"%(universe,channel+2), 'f', self.cb_pb_index)
            self.server.add_method("/%i/dmx/%i"%(universe,channel+3), 'f', self.cb_loadfile)
            self.server.add_method("/%i/dmx/%i"%(universe,channel+4), 'f', self.cb_pb_next)
            self.server.add_method("/%i/dmx/%i"%(universe,channel+5), 'f', self.cb_pb_prev)
            self.server.add_method("/%i/dmx/%i"%(universe,channel+6), 'f', self.cb_brightness)
            self.server.add_method("/%i/dmx/%i"%(universe,channel+7), 'f', self.cb_contrast)
            self.server.add_method("/%i/dmx/%i"%(universe,channel+8), 'f', self.cb_gamma)
            self.server.add_method("/%i/dmx/%i"%(universe,channel+9), 'f', self.cb_hue)
            self.server.add_method("/%i/dmx/%i"%(universe,channel+10), 'f', self.cb_saturation)
            self.server.add_method("/%i/dmx/%i"%(universe,channel+11), 'f', self.cb_volume)
            self.server.add_method("/%i/dmx/%i"%(universe,channel+12), 'f', self.cb_osd)
            self.server.add_method("/%i/dmx/%i"%(universe,channel+13), 'f', self.cb_fullscreen)
            self.server.add_method("/%i/dmx/%i"%(universe,channel+14), 'f', self.cb_inpoint)
            self.server.add_method("/%i/dmx/%i"%(universe,channel+15), 'f', self.cb_outpoint)
            self.server.add_method("/%i/dmx/%i"%(universe,channel+16), 'f', self.cb_cue)
            self.server.add_method("/%i/dmx/%i"%(universe,channel+17), 'f', self.cb_startreplay)
            self.server.add_method(None, None, self.osc_fallback)

            self.server.start()

            cmd = ['mpv', '--input-unix-socket=%s'%(spath), '--keep-open=always', '--idle', '--quiet', '--ao=pulse', '--osc=no'] + extargs
            self.proc = subprocess.Popen(args=cmd, shell=False)

            self.mpvsock = socket.socket(socket.AF_UNIX)

            def try_connect(socket, path):
                try:
                    socket.connect(path)
                    return True
                except ConnectionRefusedError:
                    return False
                
            while try_connect(self.mpvsock, spath) == False:
                time.sleep(1)

            self.statusbar.push(self.context, "connected")
            self.starttoggle.set_label("Close")

        except liblo.ServerError as err:
            self.statusbar.push(self.context, "ServerError: {0}".format(err))
        except OSError as err:
            self.statusbar.push(self.context, "OSERROR: {0}".format(err))
        except:
            self.statusbar.push(self.context, "Unknown Error")

    def stop_bridge(self):
        if self.server:
            self.server.stop()
            self.server.free()
            del self.server
            self.server = None
            self.starttoggle.set_active(False)

        if self.mpvsock:
            self.mpvsock.close()

        if self.proc:
            self.proc.terminate()

        self.statusbar.push(self.context, "disconnected")
        self.starttoggle.set_label("Start")
            
    def start_monitor(self):
        self.replay_file = ""
        self.inpoint = ""
        self.outpoint = ""

        mask = pyinotify.IN_CREATE | pyinotify.IN_CLOSE_WRITE  # watched events
        self.wdd = self.watch_manager.add_watch(self.rp_folder, mask, rec=False)

    def stop_monitor(self):
        self.watch_manager.rm_watch(self.rp_folder, self.wdd.values())            

    def on_start_toggled(self, widget):
        if widget.get_active():
            print("Application.on_start_toggled - active")
            self.start_bridge()
        else:
            print("Application.on_start_toggled - not active")
            self.stop_bridge()

    def on_port_changed(self, widget):
        self.stop_bridge()

    def on_universe_changed(self, widget):
        self.stop_bridge()

    def on_address_changed(self, widget):
        self.stop_bridge()

    def on_fifo_activate(self, widget):
        self.stop_bridge()

    def on_extargs_activate(self, widget):
        self.stop_bridge()

    def set_playback_folder(self):
        folder = self.filechooser_playback.get_file().get_path()
        filelist = list()
        for i in os.listdir(folder):
            fpath = os.path.join(folder, i)
            content_type, val = Gio.content_type_guess(filename=fpath, data=None)
            print(fpath, content_type, Gio.content_type_is_a(content_type, 'audio/*') or Gio.content_type_is_a(content_type, 'image/*') or Gio.content_type_is_a(content_type, 'video/*'))
            if Gio.content_type_is_a(content_type, 'audio/*') or Gio.content_type_is_a(content_type, 'image/*') or Gio.content_type_is_a(content_type, 'video/*'):
                filelist.append(fpath)
        filelist = sorted(filelist)
        if (len(filelist)):
            self.pb_model.clear()
            for i in range(len(filelist)):
                print("model append ", len(self.pb_model), i, filelist[i])
                self.pb_model.append([i, filelist[i]])

            #tp = Gtk.TreePath.new_from_indices([0])
            tp = Gtk.TreePath.new_from_string("0")
            iter = self.pb_model.get_iter(tp)
            self.pb_selection.select_iter(iter)
        self.pb_folder = folder

    def on_playbackfolder_set(self, widget):
        self.set_playback_folder()

    def on_replayfolder_set(self, widget):
        self.rp_folder = widget.get_file().get_path()
        self.stop_monitor()
        self.start_monitor()
        
#####################################################################
#       Action Callbacks
#####################################################################
    
    def on_load(self, widget):
        dialog = Gtk.FileChooserDialog("Please choose a file", self.window,
                                       Gtk.FileChooserAction.OPEN,
                                       ("_Cancel", Gtk.ResponseType.CANCEL,
                                        "_Open", Gtk.ResponseType.OK))
    
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            filename = dialog.get_filename()
            parser = Json.Parser.new()
            parser.load_from_file(filename)
            node = parser.get_root()
            
            reader = Json.Reader.new(node)
            
            reader.read_member('player')

            reader.read_member('port')
            self.port.set_value(reader.get_int_value())
            reader.end_element()

            reader.read_member('universe')
            self.universe.set_value(reader.get_int_value())
            reader.end_element()

            reader.read_member('channel')
            self.channel.set_value(reader.get_int_value())
            reader.end_element()

            reader.read_member('extargs')
            self.extargs.set_text(reader.get_string_value())
            reader.end_element()

            reader.read_member('folder')
            folder = 'file:///%s'%(reader.get_string_value())
            self.filechooser_playback.set_current_folder_uri(folder)
            reader.end_element()
            self.set_playback_folder()

            reader.end_member()


            reader.read_member('replay')
            
            reader.read_member('folder')
            self.rp_folder = reader.get_string_value()
            self.filechooser_replay.set_current_folder_uri('file:///%s'%(self.rp_folder))
            reader.end_element()

            reader.read_member('tree')
            for i in range(reader.count_elements()):
                reader.read_element(i)
                cols = list()
                for j in range(reader.count_elements()):
                    reader.read_element(j)
                    cols.append(reader.get_string_value())
                    reader.end_element()
                reader.end_element()
                self.rp_model.append(cols)
            reader.end_element()

            reader.end_member()

        dialog.destroy()
        self.filename = filename

    def save(self, filename):
        builder = Json.Builder.new()
        app = builder.begin_object()
        
        member = app.set_member_name('player')
        player = member.begin_object()
        port = player.set_member_name('port')
        port.add_int_value(self.port.get_value())
        uni = player.set_member_name('universe')
        uni.add_int_value(self.universe.get_value())
        channel = player.set_member_name('channel')
        channel.add_int_value(self.channel.get_value())
        extargs = player.set_member_name('extargs')
        extargs.add_string_value(self.extargs.get_text())
        pb = player.set_member_name('folder')
        pb.add_string_value(self.pb_folder)            
        player.end_object()
        
        member = app.set_member_name('replay')
        rp = member.begin_object()
        f = player.set_member_name('folder')
        f.add_string_value(self.rp_folder)
        tree = player.set_member_name('tree')

        rows = tree.begin_array()
        model = self.rp_model
        iter = model.get_iter_first()
        while iter != None:
            row = rows.begin_array()
            row.add_string_value(model[iter][Application.COL_REPLAY_FILE])
            row.add_string_value(model[iter][Application.COL_REPLAY_IN])
            row.add_string_value(model[iter][Application.COL_REPLAY_OUT])
            row.add_string_value(model[iter][Application.COL_REPLAY_START])
            iter = model.iter_next(iter)
            row.end_array()
        rows.end_array()
        rp.end_object()
        app.end_object()
        
        gen = Json.Generator.new()
        gen.set_root(builder.get_root())
        gen.set_pretty(True)
        gen.to_file(filename)
        self.filename = filename        
        
    def on_save(self, widget):
        if self.filename:
            self.save(self.filename)
        else:
            self.on_saveas(None)
            
    def on_saveas(self, widget):
        dialog = Gtk.FileChooserDialog("Please choose a file", self.window,
                                       Gtk.FileChooserAction.SAVE,
                                       ("_Cancel", Gtk.ResponseType.CANCEL,
                                        "_Save", Gtk.ResponseType.OK))
                                        
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            self.save(dialog.get_filename())

        dialog.destroy()
        
    def on_config(self, widget):
        self.configdialog.run()
        if self.server and self.server.port != int(self.port.get_value()):
            self.stop_bridge()
            self.start_bridge()
        self.configdialog.hide()    
    
    def on_about(self, widget):
        about = Gtk.AboutDialog()
        about.set_copyright("(c) Thomas Achtner 2015")
        about.set_license("GPLv3")
        about.set_comments("OSC Bridge for mplayer to use with QLC+")
        about.set_website("https://github.com/offtools/oscmplayer")
        about.set_logo(GdkPixbuf.Pixbuf.new_from_file('logo.png'))
        about.run()
        about.destroy()

    def on_quit(self, widget):
        self.stop_bridge()
        self.stop_monitor()
        self.notifier.stop()
        Gtk.main_quit()


#####################################################################
#       Player Commands
#####################################################################
    def _send_command(self, msg):
        d = dict()
        d['command'] = msg
        s = "%s\n"%(json.dumps(d))
        self.mpvsock.send(s.encode())

    def send_command(self, cmd, *args):
        l=list([cmd])
        [l.append(i) for i in args]
        self._send_command(l)

    def send_property(self, prop, *args):
        l=list(['set_property', prop])
        [l.append(i) for i in args]
        self._send_command(l)

    def send_property_string(self, prop, *args):
        l=list(['set_property_string', prop])
        [l.append(i) for i in args]
        self._send_command(l)
        
    def wait_reply(self, msgtype, msgvalue, timeout=10):
        start = time.time()
        tdiff = time.time()-start
        while tdiff < 10:
            tdiff = time.time() - start
            ret = self.mpvsock.recvmsg(1024)
            if len(ret[0].decode()):
                for i in ret[0].decode().split('\n'):
                    if len(i):
                        o = json.loads(i)
                        if msgtype in o and o[msgtype] == msgvalue:
                            return

    def empty_socket(self):
        self.mpvsock.setblocking(0)
        try:
            while len(self.mpvsock.recv(1024)) >=1024:
                pass
        except BlockingIOError:
            pass
        self.mpvsock.setblocking(1)

    def player_load(self):
        model, iter = self.pb_selection.get_selected()
        if (iter):
            filename = model[iter][Application.COL_FILEPATH]
            self.rp_speed.set_value(0)
            self.send_property_string('pause', 'no')
            self.player_status = Application.PLAYER_STATUS_PLAYING
            self.send_command('loadfile', filename)

    def player_pause(self):
        if self.player_status == Application.PLAYER_STATUS_PAUSED:
            self.send_property_string('pause', 'no')
            self.player_status = Application.PLAYER_STATUS_PLAYING
        elif self.player_status == Application.PLAYER_STATUS_PLAYING:
            self.send_property_string('pause', 'yes')
            self.player_status = Application.PLAYER_STATUS_PAUSED
            
    def player_stop(self):
        self.send_command("stop")
        self.player_status = Application.PLAYER_STATUS_STOPPED

    def player_next(self):
        model, iter = self.pb_selection.get_selected()
        iter = model.iter_next(iter)
        if (iter):
            self.pb_selection.select_iter(iter)
            file = model[iter][Application.COL_FILEPATH]
            #self.send_command('loadfile',  "%s"%(file))
            p = self.pb_model.get_path(iter)
            self.pb_tree.scroll_to_cell(p)
            self.player_load()

    def player_prev(self):
        model, iter = self.pb_selection.get_selected()
        iter = model.iter_previous(iter)
        if (iter):
            self.pb_selection.select_iter(iter)
            #self.send_command('loadfile', "%s"%(model[iter][Application.COL_FILEPATH]))
            p = self.pb_model.get_path(iter)
            self.pb_tree.scroll_to_cell(p)
            self.player_load()
            
#####################################################################
#       GTK Player Callbacks
#####################################################################

    def on_player_play(self, widget):
        self.player_load()
            
    def on_player_pause(self, widget):
        self.player_pause()

    def on_player_stop(self, widget):
        self.player_stop()

    def on_player_next(self, widget):
        self.player_next()

    def on_player_prev(self, widget):
        self.player_prev()

#####################################################################
#       OBS Replay 
#####################################################################
    def set_replay_in(self):
        f, t = self.event_handler.current()
        if (f):
            self.replay_file = f
            self.inpoint = str(datetime.datetime.now())

    def set_replay_out(self):
        f, t = self.event_handler.current()
        if (f):

            # check if replay file was set
            if (self.replay_file == ""):
                self.replay_file = f
                
            if (f != self.replay_file):
                # File changed  
                self.inpoint = ""
                self.outpoint = ""
                self.replay_file = ""              
                return

            # check if inpoint was set, otherwise inpoint is 0
            if(self.inpoint == ""):
                self.inpoint = t
                
            self.outpoint = str(datetime.datetime.now())

    def set_replay_cue(self):
        f, t = self.event_handler.current()
        if (f):
            # File changed  ?
            if (f != self.replay_file):
                self.inpoint = ""
                self.outpoint = ""
                self.replay_file = ""
                return

            if (len(self.inpoint) and len(self.outpoint)):
                iter = self.rp_model.append([f, self.inpoint, self.outpoint, t])
                self.rp_selection.select_iter(iter)

    def start_replay(self):
        model, iter = self.rp_selection.get_selected()
        if (iter):
            file = model[iter][Application.COL_REPLAY_FILE]
            preroll = int(self.rp_preroll.get_value())
            
            fmt = "%Y-%m-%d %H:%M:%S"
            inp = datetime.datetime.strptime(model[iter][Application.COL_REPLAY_IN][:-7], fmt)
            out = datetime.datetime.strptime(model[iter][Application.COL_REPLAY_OUT][:-7], fmt)
            start = datetime.datetime.strptime(model[iter][Application.COL_REPLAY_START][:-7], fmt)

            inp = inp.hour*3600 + inp.minute*60 + inp.second
            out = out.hour*3600 + out.minute*60 + out.second
            start = start.hour*3600 + start.minute*60 + start.second

            seek = inp - start
            if seek - preroll > 0:
                seek = seek - preroll
            else:
                seek = 0

            dur = out - start
 
            self.empty_socket()
            self.send_command('loadfile', file)
            self.wait_reply('event', 'playback-restart')
            self.send_property_string("pause", "yes")
            self.player_status = Application.PLAYER_STATUS_PAUSED
            if seek > 0:
                self.send_command("seek", seek, "absolute", "exact")

    def stop_replay(self):
        pass

#####################################################################
#       GTK  Replay Callbacks
#####################################################################
    def on_replay_in(self, widget):
        self.set_replay_in()
        
    def on_replay_out(self, widget):
        self.set_replay_out()

    def on_replay_queue(self, widget):
        self.set_replay_cue()

    def on_replay_play(self, widget):
        self.start_replay()
        
    def on_replay_speed_changed(self, adj):
        value = adj.get_value()
        speed = 1
        if value == 0:
            speed = 1
        elif value < 0:
            speed
            speed = 1 + value
        elif value > 0:
            speed = value*9+1

        self.rp_speed_label.set_text("%.2f"%(speed))
        self.send_property_string('speed', "%.2f"%(speed))

    def on_replay_speed_reset(self, widget):
        self.rp_speed.set_value(0)

#####################################################################
#       OSC
#####################################################################
    def osc_fallback(self, path, args):
        print ("oscbridge: received unknown message", path, args)

    def cb_stop(self, path, args):
        if args[0] == 1.0:
            self.player_stop()

    def cb_pause(self, path, args):
        if args[0] == 1.0:
            self.player_pause()
#            if self.player_status == Application.PLAYER_STATUS_PAUSED:
#                self.send_property_string('pause', 'no')
#                self.player_status = Application.PLAYER_STATUS_PLAYING
#            elif self.player_status == Application.PLAYER_STATUS_PLAYING:
#                self.send_property_string('pause', 'yes')
#                self.player_status = Application.PLAYER_STATUS_PAUSED

    def cb_pb_next(self, path, args):
        if args[0] == 1.0:
            self.player_next()
#            model, iter = self.pb_selection.get_selected()
#            iter = model.iter_next(iter)
#            if (iter):
#                self.pb_selection.select_iter(iter)
#                file = model[iter][Application.COL_FILEPATH]
#                self.send_command('loadfile',  "%s"%(file))
#                p = self.pb_model.get_path(iter)
#                self.pb_tree.scroll_to_cell(p)

    def cb_pb_prev(self, path, args):
        if args[0] == 1.0:
            self.player_prev()
#            model, iter = self.pb_selection.get_selected()
#            iter = model.iter_previous(iter)
#            if (iter):
#                self.pb_selection.select_iter(iter)
#                self.send_command('loadfile', "%s"%(model[iter][Application.COL_FILEPATH]))
#                p = self.pb_model.get_path(iter)
#                self.pb_tree.scroll_to_cell(p)

    def cb_pb_index(self, path, args):
        index = int(round(args[0]*255))
        if index < 0:
            index = 0
        elif index >= len(self.pb_model):
            index = len(self.pb_model) - 1

        tp = Gtk.TreePath.new_from_indices([index])
        iter = self.pb_model.get_iter(tp)
        self.pb_selection.select_iter(iter)
        p = self.pb_model.get_path(iter)
        self.pb_tree.scroll_to_cell(p)

    def cb_loadfile(self, path, args):
        if args[0] == 1.0:
            self.player_load()

#        if args[0] == 1.0 and args[0] < len(self.pb_model):
#            model, iter = self.pb_selection.get_selected()
#            filename = model[iter][Application.COL_FILEPATH]
#            content_type, val = Gio.content_type_guess(filename=filename, data=None)
#            self.send_property_string('pause', 'no')
#            self.player_status = Application.PLAYER_STATUS_PLAYING
#            self.send_command('loadfile', filename)

    def cb_brightness(self, path, args):
        brightness = int(round(args[0]*200)-100)
        self.send_property("brightness", brightness)

    def cb_contrast(self, path, args):
        contrast = int(round(args[0]*200)-100)
        self.send_property('contrast', contrast)

    def cb_gamma(self, path, args):
        gamma = int(round(args[0]*200)-100)
        self.send_property('gamma', gamma)

    def cb_hue(self, path, args):
        hue = int(round(args[0]*200)-100)
        self.send_property('hue',hue)

    def cb_saturation(self, path, args):
        saturation = int(round(args[0]*200)-100)
        self.send_property('saturation', saturation)

    def cb_volume(self, path, args):
        volume = int(round(args[0]*100))
        self.send_property('volume', volume)

    def cb_osd(self, path, args):
        osd = int(int(round(args[0]*255))/63)
        self.send_command('osd', osd)

    def cb_fullscreen(self, path, args):
        if args[0] > 0.5:
            self.send_property_string('fullscreen', "yes")
        else:
            self.send_property_string('fullscreen', "no")

    def cb_inpoint(self, path, args):
        if args[0] == 1.0:
            self.set_replay_in()
            
    def cb_outpoint(self, path, args):
        if args[0] == 1.0:
            self.set_replay_out()

    def cb_cue(self, path, args):
        if args[0] == 1.0:
            self.set_replay_cue()

    def cb_startreplay(self, path, args):
        if args[0] == 1.0:
            self.start_replay()

if __name__ == "__main__":
    app = Application()
    app.run()
