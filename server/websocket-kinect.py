#!/usr/bin/env python

import sys
from twisted.internet import reactor, threads
from autobahn.websocket import WebSocketServerFactory, WebSocketServerProtocol, listenWS
import freenect
import signal
import numpy
import pylzma

class BroadcastServerProtocol(WebSocketServerProtocol):
  
  def onOpen(self):
    self.factory.register(self)
  
  def connectionLost(self, reason):
    WebSocketServerProtocol.connectionLost(self, reason)
    self.factory.unregister(self)

class BroadcastServerFactory(WebSocketServerFactory):
  
  protocol = BroadcastServerProtocol
  
  def __init__(self, url):
    WebSocketServerFactory.__init__(self, url)
    self.clients = []
    self.tickSetup()
    
  def tickSetup(self):
    self.dataSent = 0
    reactor.callLater(1, self.tick)
  
  def tick(self):
    print '%d bytes/sec' % self.dataSent
    self.tickSetup()
  
  def register(self, client):
    if not client in self.clients:
      print "registered client: " + client.peerstr
      self.clients.append(client)
  
  def unregister(self, client):
    if client in self.clients:
      print "unregistered client: " + client.peerstr
      self.clients.remove(client)
  
  def broadcast(self, msg, binary = False):
    self.dataSent += len(msg)
    for c in self.clients:
      c.sendMessage(msg, binary)

class Kinect:
  
  def __init__(self):
    useEvery = 4
    self.h = 480 / useEvery
    self.w = 640 / useEvery
    self.useCols, self.useRows = numpy.indices((self.h, self.w))
    self.useCols *= useEvery
    self.useRows *= useEvery
    
    self.keyFrameEvery = 30
    self.currentFrame = 0
    
    self.rgb = None
  
  def depthCallback(self, dev, depth, timestamp):
    if self.rgb == None: return
    
    # === depths
    
    # resize grid
    depth = depth[self.useCols, self.useRows]
    
    # rescale depths
    numpy.clip(depth, 0, 2 ** 10 - 1, depth)
    depth >>= 2
    
    # calculate quadrant averages
    h, w = self.h, self.w
    halfH, halfW = h / 2, w / 2
    qtl = numpy.mean(depth[0:halfH, 0:halfW])
    qtr = numpy.mean(depth[0:halfH, halfW:w])
    qbl = numpy.mean(depth[halfH:h, 0:halfW])
    qbr = numpy.mean(depth[halfH:h, halfW:w])
    
    # calculate diff from last frame (unless it's a keyframe)
    keyFrame = self.currentFrame == 0
    diffDepth = depth if keyFrame else (depth - self.lastDepth) % 256
    
    # === rgb
    rgb = self.rgb[self.useCols, self.useRows]
    lightness = numpy.mean(rgb, axis = 2)
    
    # print lightness.ravel().astype(numpy.uint8)
    
    # smush data together
    data = numpy.concatenate(([keyFrame, qtl, qtr, qbl, qbr], diffDepth.ravel(), lightness.ravel()))
    
    # compress and broadcast
    crunchedData = pylzma.compress(data.astype(numpy.uint8), dictionary = 16)  # default dict: 23 -> 2 ** 23 -> 8MB
    reactor.callFromThread(factory.broadcast, crunchedData, True)
    
    # setup for next frame
    self.lastDepth = depth
    self.currentFrame += 1
    self.currentFrame %= self.keyFrameEvery
  
  def rgbCallback(self, dev, rgb, timestamp):
    self.rgb = rgb
  
  def bodyCallback(self, *args):
    if not self.kinecting: raise freenect.Kill
  
  def run(self):
    self.kinecting = True
    reactor.callInThread(freenect.runloop, depth = self.depthCallback, video = self.rgbCallback, body = self.bodyCallback)
  
  def stop(self):
    self.kinecting = False

def signalHandler(signum, frame):
  kinect.stop()
  reactor.stop()

port = sys.argv[1] if len(sys.argv) > 1 else "9000"
url = "ws://localhost:" + port

signal.signal(signal.SIGINT, signalHandler)
print '>>> Broadcasting at %s --- Press Ctrl-C to stop <<<' % url

kinect = Kinect()
kinect.run()
factory = BroadcastServerFactory(url)
listenWS(factory)

reactor.run()
