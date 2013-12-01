"""
This example demonstrates how to embed matplotlib WebAgg interactive
plotting in your own tornado web application.
"""

import io

import tornado.web
import tornado.wsgi
import tornado.httpserver
import tornado.ioloop
import tornado.websocket


import matplotlib
matplotlib.use('webagg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_webagg_core import (
    FigureManagerWebAgg, new_figure_manager_given_figure)

import numpy as np
import pandas as pd

import json


def get_data(num):
    """fake some data"""
    idx = pd.date_range(end='2013-12-31', periods=100)
    df = pd.DataFrame(np.random.random((100, 15)) * 10 * int(num),
                      columns=list('ABCDEFGHIJKLMNO'), index=idx)
    return df


def create_figure(data, x, left_y, right_y):
    style = '-' if x is None else '.'
    fig, ax = plt.subplots()
    if isinstance(x, list):
        x = x[0]
    x = x if x != 'index' else None
    print 'x: %s, left_y: %s, right_y: %s' % (x, left_y, right_y)
    cols = left_y + right_y
    if x is not None:
        cols = cols + [x]
    data[cols].plot(ax=ax, x=x, secondary_y=right_y, style=style)
    return fig



class MainPage(tornado.web.RequestHandler):
    """
    Serves the main page
    """
    def get(self):
        self.render('index.html')


class PlotPage(tornado.web.RequestHandler):
    """
    Serves the plot page.
    """

    def get(self):
        self._finish_request('get')

    def post(self):
        self._finish_request('post')

    def _finish_request(self, kind):
        print '\n\n' + '=' * 80
        print 'New %s request' % kind
        print '=' * 80 + '\n'
        data_id = int(self.request.uri.strip('/DataFrame'))
        print 'get data for data id %d' % data_id
        data = get_data(data_id)
        if kind == 'get':
            print 'create figure for "get" request with args:'
            fig = create_figure(data, None, ['A'], [])
        elif kind == 'post':
            args = self.request.arguments
            print 'create figure for "post" request with args:'
            print args
            x = args.get('x', None)
            left_y = args.get('left_y', [])
            right_y = args.get('right_y', [])
            fig = create_figure(data, x, left_y, right_y)
            print id(fig)
        else:
            raise TypeError('kind must be "get" or "post"')
        fignum = id(fig)
        manager = new_figure_manager_given_figure(fignum, fig)
        self.application.figures[fignum] = (fig, manager)
        print 'created figure %d and %s' % (fignum, repr(manager))
        ws_uri = "ws://{req.host}/".format(req=self.request)
        y_cols = list(data.columns)
        x_cols = y_cols[:]
        x_cols.insert(0, 'index')
        self.render('plot.html', ws_uri=ws_uri, fig_id=manager.num,
                    y_cols=y_cols, x_cols=x_cols)




class MyApplication(tornado.web.Application):
    """Plotting application"""
    figures = dict()

    class MplJs(tornado.web.RequestHandler):
        """
        Serves the generated matplotlib javascript file.  The content
        is dynamically generated based on which toolbar functions the
        user has defined.  Call `FigureManagerWebAgg` to get its
        content.
        """
        def get(self):
            self.set_header('Content-Type', 'application/javascript')
            js_content = FigureManagerWebAgg.get_javascript()
            with open('static/mpl.js', 'r') as fh:
                local_content = fh.read()
            self.write(local_content)

    class Download(tornado.web.RequestHandler):
        """
        Handles downloading of the figure in various file formats.
        """
        def get(self, fmt):
            fignum = int(fignum)
            manager = Gcf.get_fig_manager(fignum)

            mimetypes = {
                'ps': 'application/postscript',
                'eps': 'application/postscript',
                'pdf': 'application/pdf',
                'svg': 'image/svg+xml',
                'png': 'image/png',
                'jpeg': 'image/jpeg',
                'tif': 'image/tiff',
                'emf': 'application/emf'
            }

            self.set_header('Content-Type', mimetypes.get(fmt, 'binary'))

            buff = io.BytesIO()
            manager.canvas.print_figure(buff, format=fmt)
            self.write(buff.getvalue())

    class WebSocket(tornado.websocket.WebSocketHandler):
        """
        A websocket for interactive communication between the plot in
        the browser and the server.

        In addition to the methods required by tornado, it is required to
        have two callback methods:

            - ``send_json(json_content)`` is called by matplotlib when
              it needs to send json to the browser.  `json_content` is
              a JSON tree (Python dictionary), and it is the responsibility
              of this implementation to encode it as a string to send over
              the socket.

            - ``send_binary(blob)`` is called to send binary image data
              to the browser.
        """
        supports_binary = True

        def open(self, fignum):
            print '-' * 80
            print 'request to open the websocket'
            print '-' * 80
            print self.request
            print 'fignum', fignum
            print 'application.figures'
            print self.application.figures

            self.fignum = int(fignum)
            # Register the websocket with the FigureManager.
            manager = self.application.figures[self.fignum][1]
            manager.add_web_socket(self)
            if hasattr(self, 'set_nodelay'):
                self.set_nodelay(True)
            print 'opened websocket for Figure %d' % self.fignum
            print '-' * 80
            print 'message to the socket'
            print '-' * 80


        def on_close(self):
            # When the socket is closed, deregister the websocket with
            # the FigureManager.
            fig, manager = self.application.figures.pop(self.fignum)
            manager.remove_web_socket(self)
            print '-' * 80
            print 'closed websocket for Figure %d' % self.fignum
            print '-' * 80

        def on_message(self, message):
            # Every message has a "type" and a "figure_id".
            message = json.loads(message)
            if not message['type'] == 'motion_notify':
                print 'got message', message
            if message['type'] == 'supports_binary':
                self.supports_binary = message['value']
            else:
                manager = self.application.figures[self.fignum][1]
                manager.handle_json(message)

        def send_json(self, content):
            self.write_message(json.dumps(content))

        def send_binary(self, blob):
            if self.supports_binary:
                print '-' * 80
                print 'send binary image data to the browser'
                print '-' * 80
                self.write_message(blob, binary=True)
            else:
                data_uri = "data:image/png;base64,{0}".format(
                    blob.encode('base64').replace('\n', ''))
                self.write_message(data_uri)

    def __init__(self):

        super(MyApplication, self).__init__([
            # Static files for the CSS and JS
            (r'/_static/(.*)',
            #(r'/(.*)',
             tornado.web.StaticFileHandler,
             {'path': FigureManagerWebAgg.get_static_file_path()}),

            (r'/', MainPage),

            # The pages that contain the plot (or maybe the plots)
            (r'/DataFrame\d', PlotPage),

            (r'/mpl.js', self.MplJs),

            # Sends images and events to the browser, and receives
            # events from the browser
            (r'/([0-9]+)/ws', self.WebSocket),

            # Handles the downloading (i.e., saving) of static images
            (r'/download.([a-z0-9.]+)', self.Download),

            ],
            static_path='static',
            template_path='templates',
            debug=True
            )


if __name__ == "__main__":
    application = MyApplication()

    http_server = tornado.httpserver.HTTPServer(application)
    http_server.listen(8080)

    print("http://127.0.0.1:8080/")
    print("Press Ctrl+C to quit")

    tornado.ioloop.IOLoop.instance().start()
