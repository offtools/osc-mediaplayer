#!/bin/python

import os
import subprocess
import liblo
import pyinotify
import datetime
from os.path import expanduser

import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gtk
from gi.repository import Gio
from gi.repository import GdkPixbuf
from gi.repository import Json

class oscbridge(liblo.ServerThread):
    def __init__(self, universe, channel, port, fifo, extargs):
        super().__init__(port)

        self.__fifoname = fifo

        os.mkfifo(self.__fifoname)
        cmd = ['mplayer', '-ao', 'pulse', '-fixed-vo', '-idle', '-quiet', '-slave', '-input', 'file=%s'%(self.__fifoname)] + extargs
        self.__proc = subprocess.Popen(cmd)
        self.__fifo = open(self.__fifoname, 'w')
        self.__fifo.flush()

    def __del__(self):
        self.__proc.terminate()
        os.remove(self.__fifoname)

    def send_command(self, msg):
        m = '%s\n' % (msg)
        self.__fifo.write(m)
        self.__fifo.flush()

    def set_property(self, prop, argument):
        self.send_command('set_property %s %d'%(prop, argument))

    def start(self):
        self.add_method(None, None, self.osc_fallback)
        super().start()

    def stop(self):
        super().stop()

    def quit(self):
        self.send_command('quit\n')

    def osc_fallback(self, path, args):
        print ("oscbridge: received unknown message", path, args)

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

    def __init__(self):
        handlers = {
            "on_quit": self.on_quit,
            "on_start_toggled": self.on_start_toggled,
            "on_playbackfolder_set": self.on_playbackfolder_set,
            "on_replayfolder_set": self.on_replayfolder_set,
            "on_about": self.on_about,
            "on_replay_in": self.on_replay_in,
            "on_replay_out": self.on_replay_out,
            "on_replay_queue": self.on_replay_queue,
            "on_replay_play": self.on_replay_play,
            "on_config_response": self.on_config_response,
            "on_config_close": self.on_config_close,
            "on_config": self.on_config,
            "on_port_changed": self.on_port_changed,
            "on_universe_changed": self.on_universe_changed,
            "on_address_changed": self.on_address_changed,
            "on_fifo_activate": self.on_fifo_activate,
            "on_extargs_activate": self.on_extargs_activate
        }

        # init gtk stuff
        builder = Gtk.Builder()
        builder.add_from_file("oscmplayer.ui")
        builder.connect_signals(handlers)

        self.window = builder.get_object("window")
        self.port = builder.get_object("adjustment_port")
        self.universe = builder.get_object("adjustment_universe")
        self.channel = builder.get_object("adjustment_channel")
        self.fifo = builder.get_object("fifo")
        self.statusbar = builder.get_object("statusbar")
        self.extargs = builder.get_object("extargs")
        self.model = builder.get_object("liststore")
        self.tree = builder.get_object("treeview")
        self.selection = builder.get_object("treeview-selection")
        self.scrollwin = builder.get_object("scrolledwindow1")
        self.context = self.statusbar.get_context_id("mplayer osc bridge")
        self.starttoggle =  builder.get_object("playtoggle")
        self.replay_model = builder.get_object("liststore1")
        self.replay_selection = builder.get_object("treeview-selection2")
        self.configdialog =  builder.get_object("configdialog")
        self.configdialog.add_button("Close", Gtk.ResponseType.OK)
        
        home = expanduser("~")

        self.folder_replay = home
        self.folder_playback = home
        self.filechooser_replay = builder.get_object("filechooser_replay")
        self.filechooser_replay.set_current_folder_uri('file:///%s'%(home))
        filechooser_playback = builder.get_object("filechooser_playback")
        filechooser_playback.set_current_folder_uri('file:///%s'%(home))       

        menuitem = builder.get_object("menuitem_file_quit")
        menuitem.set_sensitive(True)
        menuitem = builder.get_object("menuitem_file_config")
        menuitem.set_sensitive(True)

        self.started = False
        self.oscbridge = None

        # OBS
        self.start_monitor()

#####################################################################
#       GTK
#####################################################################

    def run(self):
        self.window.show_all()
        Gtk.main()

    def start_bridge(self):
        try:
            if self.oscbridge:
                del self.oscbridge
                
            universe = int(self.universe.get_value())-1
            port = int(self.port.get_value())
            channel = int(self.channel.get_value())-1
            mplfifo = self.fifo.get_text()
            extargs = self.extargs.get_text().split()

            self.oscbridge = oscbridge(universe, channel, port, mplfifo, extargs)
            self.oscbridge.add_method("/%i/dmx/%i"%(universe,channel), 'f', self.cb_stop)
            self.oscbridge.add_method("/%i/dmx/%i"%(universe,channel+1), 'f', self.cb_pause)
            self.oscbridge.add_method("/%i/dmx/%i"%(universe,channel+2), 'f', self.cb_index)
            self.oscbridge.add_method("/%i/dmx/%i"%(universe,channel+3), 'f', self.cb_loadfile)
            self.oscbridge.add_method("/%i/dmx/%i"%(universe,channel+4), 'f', self.cb_next)
            self.oscbridge.add_method("/%i/dmx/%i"%(universe,channel+5), 'f', self.cb_prev)
            self.oscbridge.add_method("/%i/dmx/%i"%(universe,channel+6), 'f', self.cb_brightness)
            self.oscbridge.add_method("/%i/dmx/%i"%(universe,channel+7), 'f', self.cb_contrast)
            self.oscbridge.add_method("/%i/dmx/%i"%(universe,channel+8), 'f', self.cb_gamma)
            self.oscbridge.add_method("/%i/dmx/%i"%(universe,channel+9), 'f', self.cb_hue)
            self.oscbridge.add_method("/%i/dmx/%i"%(universe,channel+10), 'f', self.cb_saturation)
            self.oscbridge.add_method("/%i/dmx/%i"%(universe,channel+11), 'f', self.cb_volume)
            self.oscbridge.add_method("/%i/dmx/%i"%(universe,channel+12), 'f', self.cb_osd)
            self.oscbridge.add_method("/%i/dmx/%i"%(universe,channel+13), 'f', self.cb_fullscreen)

            self.oscbridge.start()

        except liblo.ServerError as err:
            self.statusbar.push(self.context, "ServerError: {0}".format(err))
        except OSError as err:
            self.statusbar.push(self.context, "OSERROR: {0}".format(err))

    def stop_bridge(self):
        del self.oscbridge
        self.oscbridge = None

    def start_monitor(self):
        self.wm = pyinotify.WatchManager()  # Watch Manager
        mask = pyinotify.IN_CREATE | pyinotify.IN_CLOSE_WRITE  # watched events

        self.ev = EventHandler()
        self.notifier = pyinotify.ThreadedNotifier(self.wm, self.ev)
        self.notifier.start()

        self.wdd = self.wm.add_watch(self.folder_replay, mask, rec=False)

        self.replay_file = ""
        self.inpoint = ""
        self.outpoint = ""

    def stop_monitor(self):
        pass

    def on_start_toggled(self, widget):
        if widget.get_active():
            self.start_bridge()
            self.statusbar.push(self.context, "connected")
            self.starttoggle.set_label("Close")
        else:
            self.stop_bridge()
            self.statusbar.push(self.context, "disconnected")
            self.starttoggle.set_label("Start")

    def on_config_close(self, widget):
        pass
    
    def on_config_response(self, widget, response):
        pass
    
    def on_config(self, widget):
        self.configdialog.run()
        if self.oscbridge and self.oscbridge.port != int(self.port.get_value()):
            self.stop_bridge()
        self.start_bridge()
        self.configdialog.hide()

    def on_port_changed(self, widget):
        pass

    def on_universe_changed(self, widget):
        pass

    def on_address_changed(self, widget):
        pass

    def on_fifo_activate(self, widget):
        pass

    def on_extargs_activate(self, widget):
        pass

    def on_playbackfolder_set(self, widget):
        folder = widget.get_file().get_path()

        filelist = list()
        for i in os.listdir(folder):
            fpath = os.path.join(folder, i)
            content_type, val = Gio.content_type_guess(filename=fpath, data=None)
            print(fpath, content_type, Gio.content_type_is_a(content_type, 'audio/*') or Gio.content_type_is_a(content_type, 'image/*') or Gio.content_type_is_a(content_type, 'video/*'))
            if Gio.content_type_is_a(content_type, 'audio/*') or Gio.content_type_is_a(content_type, 'image/*') or Gio.content_type_is_a(content_type, 'video/*'):
                filelist.append(fpath)
        filelist = sorted(filelist)
        if (len(filelist)):
            self.model.clear()
            for i in range(len(filelist)):
                print("model append ", len(self.model), i, filelist[i])
                self.model.append([i, filelist[i]])

            #tp = Gtk.TreePath.new_from_indices([0])
            tp = Gtk.TreePath.new_from_string("0")
            iter = self.model.get_iter(tp)
            self.selection.select_iter(iter)

    def on_replayfolder_set(self, widget):
        folder = widget.get_file().get_path()
        
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
        if (self.oscbridge):
            self.oscbridge.quit()
            self.oscbridge.stop()
        #folder = self.filechooser_replay.get_file().get_path()
        self.wm.rm_watch(self.folder_replay, self.wdd.values())            
        self.notifier.stop()
        Gtk.main_quit()

#####################################################################
#       OBS Replay
#####################################################################
    def on_replay_in(self, widget):
        f, t = self.ev.current()
        if (f):
            self.replay_file = f
            self.inpoint = str(datetime.datetime.now())

    def on_replay_out(self, widget):
        f, t = self.ev.current()
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

    def on_replay_queue(self, widget):
        f, t = self.ev.current()
        if (f):
            # File changed  ?
            if (f != self.replay_file):
                self.inpoint = ""
                self.outpoint = ""
                self.replay_file = ""
                return

            if (len(self.inpoint) and len(self.outpoint)):
                self.replay_model.append([f, self.inpoint, self.outpoint, t])
                
                
    def on_replay_play(self, widget):
        model, iter = self.replay_selection.get_selected()
        if (iter):
            file = model[iter][Application.COL_REPLAY_FILE]
            fmt = "%Y-%m-%d %H:%M:%S"
            inp = datetime.datetime.strptime(model[iter][Application.COL_REPLAY_IN][:-7], fmt)
            out = datetime.datetime.strptime(model[iter][Application.COL_REPLAY_OUT][:-7], fmt)
            start = datetime.datetime.strptime(model[iter][Application.COL_REPLAY_START][:-7], fmt)

            inp = inp.hour*3600 + inp.minute*60 + inp.second
            out = out.hour*3600 + out.minute*60 + out.second
            start = start.hour*3600 + start.minute*60 + start.second

            seek = inp - start
            length = out - start
            
            self.oscbridge.send_command('loadfile "%s"'%(file))
            self.oscbridge.send_command('seek %d'%(seek))

#####################################################################
#       OSC
#####################################################################

    def cb_stop(self, path, args):
        if args[0] == 1.0:
            self.oscbridge.send_command("stop")

    def cb_pause(self, path, args):
        if args[0] == 1.0: 
            self.oscbridge.send_command('pause')
                

    def cb_next(self, path, args):
        model, iter = self.selection.get_selected()
        iter = model.iter_next(iter)
        if (iter):
            self.selection.select_iter(iter)
            file = model[iter][Application.COL_FILEPATH]
            self.oscbridge.send_command('loadfile "%s"'%(file))
            p = self.model.get_path(iter)
            self.tree.scroll_to_cell(p)

    def cb_prev(self, path, args):
        model, iter = self.selection.get_selected()
        iter = model.iter_previous(iter)
        if (iter):
            self.selection.select_iter(iter)
            self.oscbridge.send_command('loadfile "%s"'%(model[iter][Application.COL_FILEPATH]))
            p = self.model.get_path(iter)
            self.tree.scroll_to_cell(p)

    def cb_index(self, path, args):
        index = int(round(args[0]*255))
        if index < 0:
            index = 0
        elif index >= len(self.model):
            index = len(self.model) - 1

        tp = Gtk.TreePath.new_from_indices([index])
        iter = self.model.get_iter(tp)
        self.selection.select_iter(iter)
        p = self.model.get_path(iter)
        self.tree.scroll_to_cell(p)

    def cb_loadfile(self, path, args):
        if args[0] == 1.0 and args[0] < len(self.model):
            model, iter = self.selection.get_selected()
            filename = model[iter][Application.COL_FILEPATH]
            content_type, val = Gio.content_type_guess(filename=filename, data=None)
            if (Gio.content_type_is_a(content_type, 'image/*')):
                self.oscbridge.send_command('loadfile "mf://%s"'%(filename))
            self.oscbridge.send_command('loadfile "%s"'%(filename))

    def cb_brightness(self, path, args):
        brightness = int(round(args[0]*200)-100)
        self.oscbridge.set_property("brightness", brightness)

    def cb_contrast(self, path, args):
        contrast = int(round(args[0]*200)-100)
        self.oscbridge.set_property('contrast', contrast)

    def cb_gamma(self, path, args):
        gamma = int(round(args[0]*200)-100)
        self.oscbridge.send_command('gamma', gamma)

    def cb_hue(self, path, args):
        hue = int(round(args[0]*200)-100)
        self.oscbridge.set_property('hue',hue)

    def cb_saturation(self, path, args):
        saturation = int(round(args[0]*200)-100)
        self.oscbridge.set_property('saturation', saturation)

    def cb_volume(self, path, args):
        volume = int(round(args[0]*100))
        self.oscbridge.set_property('volume', volume)

    def cb_osd(self, path, args):
        osd = int(int(round(args[0]*255))/63)
        self.oscbridge.send_command('osd %d'%(osd))

    def cb_fullscreen(self, path, args):
        if args[0] > 0.5:
            self.oscbridge.set_property('fullscreen', 1)
        else:
            self.oscbridge.set_property('fullscreen', 0)

if __name__ == "__main__":
    app = Application()
    app.run()
