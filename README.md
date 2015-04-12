# oscmplayer

oscmplayer is python a script to control mplayer with QLC+

OSC Path:

/[universe]/dmx/[startchannel + channel]

Universe and Start Channel are set in the Gui.
The script takes a directory which and handles it as playlist.

channel 0: stop [255]
channel 1: pause [255]
channel 2: index playlist entry [0-255]
channel 3: load file (given playlist entry index) [255]
channel 4: next entry [255]
channel 5: prev entry [255]
channel 6: brightness [0-255]
channel 7: contrast[0-255]
channel 8: gamma[0-255]
channel 9: hue [0-255]
channel 10: saturation [0-255]
channel 11: volume [0-255]
channel 12: osd [0-62 | 63-125 | 126-188 | 189-251]
channel 13: window | fullscreen |  [0-127 | 128-255]


