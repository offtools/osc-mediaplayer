#!/bin/python

import subprocess
import liblo
import os
import gi
gi.require_version('Gst', '1.0')
from gi.repository import Gtk
from gi.repository import Gio

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

class Application():
    NUMBER = 0
    FILEPATH = 1

    def __init__(self):
        handlers = {
            "on_quit": self.on_quit,
            "on_start_clicked": self.on_start_clicked,
            "on_folder_clicked": self.on_folder_clicked
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
        self.filechooser = builder.get_object("filechooserwidget")
        self.extargs = builder.get_object("extargs")
        self.model = builder.get_object("liststore")
        self.tree = builder.get_object("treeview")
        self.selection = builder.get_object("treeview-selection")
        self.scrollwin = builder.get_object("scrolledwindow1")
        self.context = self.statusbar.get_context_id("mplayer osc bridge")
        self.button =  builder.get_object("start")

        self.started = False
        self.oscbridge = None
        self.folder = None
        self.playing = False
        self.brightness = 0
        self.contrast = 0
        self.gamma = 0
        self.volume = 0
        self.hue = 0
        self.saturation = 0
        self.osd = 0

#####################################################################
#       GTK
#####################################################################

    def run(self):
        self.window.show_all()
        Gtk.main()

    def on_start_clicked(self, widget):
        if self.started == False:
            try:
                universe = int(self.universe.get_value())-1
                port = int(self.port.get_value())
                channel = int(self.channel.get_value())-1
                mplfifo = self.fifo.get_text()
                extargs = self.extargs.get_text().split()

                self.oscbridge = oscbridge(universe, channel, port, mplfifo, extargs)
                self.oscbridge.add_method("/%i/dmx/%i"%(universe,channel), 'f', self.cb_play)
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
                self.statusbar.push(self.context, "connected")

            except liblo.ServerError as err:
                self.statusbar.push(self.context, "ServerError: {0}".format(err))
            except OSError as err:
                self.statusbar.push(self.context, "OSERROR: {0}".format(err))

            self.button.set_label("Close")
            self.started = True
        else:
            self.window.destroy()

    def on_folder_clicked(self, widget):
        dialog = Gtk.FileChooserDialog("Please choose a playback folder", self.window, Gtk.FileChooserAction.SELECT_FOLDER,
            (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
             Gtk.STOCK_OPEN, Gtk.ResponseType.OK))

        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            self.folder = dialog.get_current_folder()
            filelist = list()
            for i in os.listdir(self.folder):
                fpath = os.path.join(self.folder, i)
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

                tp = Gtk.TreePath.new_from_indices([0])
                iter = self.model.get_iter(tp)
                self.selection.select_iter(iter)
        elif response == Gtk.ResponseType.CANCEL:
            print("Cancel clicked")
        dialog.destroy()

    def on_quit(self, widget):
        if (self.oscbridge):
            self.oscbridge.quit()
            self.oscbridge.stop()
        Gtk.main_quit()

#####################################################################
#       OSC
#####################################################################

    def cb_play(self, path, args):
        if args[0] == 1.0 and self.playing == False:
            self.oscbridge.send_command("pause")
            self.playing == True

    def cb_pause(self, path, args):
        if args[0] == 1.0 and self.playing == True:
            self.oscbridge.send_command('pause')
            self.playing == False

    def cb_next(self, path, args):
        if self.playing == True:
            model, iter = self.selection.get_selected()
            iter = model.iter_next(iter)
            if (iter):
                self.selection.select_iter(iter)
                file = model[iter][Application.FILEPATH]
                self.oscbridge.send_command('loadfile "%s"'%(file))
                self.playing == True
                p = self.model.get_path(iter)
                self.tree.scroll_to_cell(p)

    def cb_prev(self, path, args):
        if self.playing == True:
            model, iter = self.selection.get_selected()
            iter = model.iter_previous(iter)
            if (iter):
                self.selection.select_iter(iter)
                self.oscbridge.send_command('loadfile "%s"'%(model[iter][Application.FILEPATH]))
                self.playing == True
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
            filename = model[iter][Application.FILEPATH]
            content_type, val = Gio.content_type_guess(filename=filename, data=None)
            if (Gio.content_type_is_a(content_type, 'image/*')):
                self.oscbridge.send_command('loadfile "mf://%s"'%(filename))
            self.oscbridge.send_command('loadfile "%s"'%(filename))
            self.playing = True

    def cb_brightness(self, path, args):
        self.brightness = int(round(args[0]*200)-100)
        self.oscbridge.set_property("brightness", self.brightness)

    def cb_contrast(self, path, args):
        self.contrast = int(round(args[0]*200)-100)
        self.oscbridge.set_property('contrast', self.contrast)

    def cb_gamma(self, path, args):
        self.gamma = int(round(args[0]*200)-100)
        self.oscbridge.send_command('gamma', self.gamma)

    def cb_hue(self, path, args):
        self.hue = int(round(args[0]*200)-100)
        self.oscbridge.set_property('hue',self.hue)

    def cb_saturation(self, path, args):
        self.saturation = int(round(args[0]*200)-100)
        self.oscbridge.set_property('saturation', self.saturation)

    def cb_volume(self, path, args):
        self.volume = int(round(args[0]*100))
        self.oscbridge.set_property('volume', self.volume)

    def cb_osd(self, path, args):
        self.osd = int(int(round(args[0]*255))/63)
        self.oscbridge.send_command('osd %d'%(self.osd))

    def cb_fullscreen(self, path, args):
        if args[0] > 0.5:
            self.oscbridge.set_property('fullscreen', 1)
        else:
            self.oscbridge.set_property('fullscreen', 0)

if __name__ == "__main__":
    app = Application()
    app.run()
