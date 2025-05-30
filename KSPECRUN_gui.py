import sys
import os
import asyncio

from PySide6.QtCore import *
from PySide6.QtWidgets import (
        QApplication, QMainWindow, QPushButton, QVBoxLayout, QWidget, QMessageBox, QSizePolicy, QFileDialog,QListWidget,QListWidgetItem,
        QDialog
        )
from PySide6.QtGui import QMouseEvent, QGuiApplication
from ui_mainwindow import Ui_MainWindow
from qasync import QEventLoop, asyncSlot
from astropy.io import fits
from astropy.coordinates import Angle, SkyCoord
import astropy.units as u
from Lib.AMQ import AMQclass
import Lib.mkmessage as mkmsg
import Lib.zscale as zs
#from LAMP.lampcli import handle_lamp
import json
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from SPECTRO.speccli import handle_spec
import numpy as np
from SCIOBS.sciobscli import sciobscli
from LAMP.lampcli import handle_lamp


class MplCanvas(FigureCanvas):
    def __init__(self, parent=None,dpi=100,left=0.00,right=1.,bottom=0.0,top=1.):
        self.fig = Figure(dpi=dpi)
        self.ax = self.fig.add_subplot(111)
        self.fig.subplots_adjust(left=left,right=right,bottom=bottom,top=top) 
        self.ax.axis('off')
        super().__init__(self.fig)
        self.setParent(parent)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.updateGeometry()

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFocus()
        self._is_dragging = False
        self._last_mouse_pos = None

        # Set inital axis range
        self._initial_xlim = None
        self._initial_ylim = None

    def imshows(self, data, **kwargs):
        self.ax.clear()
        self.ax.imshow(data, **kwargs)
        self.ax.axis('on')
        self._initial_xlim = self.ax.get_xlim()
        self._initial_ylim = self.ax.get_ylim()
        self.draw()

    def plots(self,wave,flux):
        self.ax.clear()
        self.ax.plot(wave,flux,'k-')
        self.ax.axis('on')
        self.draw()

    def wheelEvent(self, event):
        # Expand and contract
        x_min, x_max = self.ax.get_xlim()
        y_min, y_max = self.ax.get_ylim()
        zoom_factor = 0.9 if event.angleDelta().y() > 0 else 1.1

        x_center = (x_min + x_max) / 2
        y_center = (y_min + y_max) / 2
        x_range = (x_max - x_min) * zoom_factor
        y_range = (y_max - y_min) * zoom_factor

        self.ax.set_xlim([x_center - x_range / 2, x_center + x_range / 2])
        self.ax.set_ylim([y_center - y_range / 2, y_center + y_range / 2])
        self.draw()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = True
            self._last_mouse_pos = event.position()
        elif event.button() == Qt.MouseButton.RightButton:
            # Right click for reset
            if self._initial_xlim and self._initial_ylim:
                self.ax.set_xlim(self._initial_xlim)
                self.ax.set_ylim(self._initial_ylim)
                self.draw()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._is_dragging and self._last_mouse_pos:
            current_pos = event.position()
            dx = current_pos.x() - self._last_mouse_pos.x()
            dy = current_pos.y() - self._last_mouse_pos.y()

            x_min, x_max = self.ax.get_xlim()
            y_min, y_max = self.ax.get_ylim()
            x_range = x_max - x_min
            y_range = y_max - y_min

            self.ax.set_xlim(x_min - dx * x_range / self.width(), x_max - dx * x_range / self.width())
            self.ax.set_ylim(y_min + dy * y_range / self.height(), y_max + dy * y_range / self.height())
            self.draw()

            self._last_mouse_pos = current_pos

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = False


class SelectTile(QDialog):
    def __init__(self, headers, data_lines, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Select Observation Plan file")
        self.selected_values = None

        self.list_widget = QListWidget()

        for line in data_lines:
            values = line.strip().split()
            # 헤더와 값 결합
            display_line = "   ".join(f"{h}: {v}" for h, v in zip(headers, values))
            item = QListWidgetItem(display_line)
            item.setData(32, values)  # Qt.UserRole = 32 → 원본 값 저장
            self.list_widget.addItem(item)

        self.list_widget.itemDoubleClicked.connect(self.select_row)

        layout = QVBoxLayout()
        layout.addWidget(self.list_widget)
        self.setLayout(layout)
        self.resize(600, 400)

    def select_row(self, item):
        self.selected_values = item.data(32)
        self.accept()


class MainWindow(QMainWindow):
    def __init__(self):

        super(MainWindow, self).__init__()
        screen = QGuiApplication.primaryScreen()
        geometry = screen.availableGeometry()

        # Window size
        screen_width = geometry.width()
        screen_height = geometry.height()

        window_width = int(screen_width * 0.8)
        window_height = int(screen_height * 0.8)

        self.resize(window_width, window_height)
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

        self.response_queue = asyncio.Queue()
        self.GFA_response_queue = asyncio.Queue()
        self.ADC_response_queue = asyncio.Queue()
        self.SPEC_response_queue = asyncio.Queue()


#Make timer (LT & UTC) 
        self.datetime = QDateTime.currentDateTime().toString()
        #self.lcd.display(datetime)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.timeout)
        self.setWindowTitle('QTimer')

        self.timer.start()


        ##### Button setting #####
        # Connect RabbitMQ server
        self.ui.pushbtn_connect.clicked.connect(self.rabbitmq_define)
        self.ui.pushbtn_connect.setCheckable(True)


        # Guiding
        self.ui.pushbtn_Guiding.clicked.connect(self.autoguiding)

        # Load Sequence
        self.ui.pushbtn_load_sequence.clicked.connect(self.load_file)
        self.ui.pushbtn_set_sequence.clicked.connect(self.load_tile)


        # Take Image
        self.ui.pushbtn_start_sequence.clicked.connect(self.take_image)


        # Subsystem function
        self.ui.pushbtn_Flat.clicked.connect(self.flat_button_clicked)
        self.ui.pushbtn_Flat.setCheckable(True)
        self.ui.pushbtn_Arc.clicked.connect(self.arc_button_clicked)
        self.ui.pushbtn_Arc.setCheckable(True)
        self.ui.pushbtn_Flat_2.clicked.connect(self.flat_button_clicked)
        self.ui.pushbtn_Flat_2.setCheckable(True)
        self.ui.pushbtn_Arc_2.clicked.connect(self.arc_button_clicked)
        self.ui.pushbtn_Arc_2.setCheckable(True)



        ##### Canvas setting #####
        self.canvas_B=MplCanvas(self,dpi=100,left=0.00,right=1.,bottom=0.0,top=1.)
        self.B_layout=QVBoxLayout(self.ui.frame_B)
        self.B_layout.addWidget(self.canvas_B)

        self.canvas_R=MplCanvas(self,dpi=100,left=0.00,right=1.,bottom=0.0,top=1.)
        self.R_layout=QVBoxLayout(self.ui.frame_R)
        self.R_layout.addWidget(self.canvas_R)


        self.canvas_G1=MplCanvas(self,dpi=100,left=0.0,right=1.,bottom=0.,top=1.)
        self.G1_layout=QVBoxLayout(self.ui.Guide1)
        self.G1_layout.addWidget(self.canvas_G1)

        self.canvas_G2=MplCanvas(self,dpi=100,left=0.0,right=1.,bottom=0.,top=1.)
        self.G2_layout=QVBoxLayout(self.ui.Guide2)
        self.G2_layout.addWidget(self.canvas_G2)

        self.canvas_G3=MplCanvas(self,dpi=100,left=0.0,right=1.,bottom=0.,top=1.)
        self.G3_layout=QVBoxLayout(self.ui.Guide3)
        self.G3_layout.addWidget(self.canvas_G3)

        self.canvas_G4=MplCanvas(self,dpi=100,left=0.0,right=1.,bottom=0.,top=1.)
        self.G4_layout=QVBoxLayout(self.ui.Guide4)
        self.G4_layout.addWidget(self.canvas_G4)

        self.canvas_G5=MplCanvas(self,dpi=100,left=0.0,right=1.,bottom=0.,top=1.)
        self.G5_layout=QVBoxLayout(self.ui.Guide5)
        self.G5_layout.addWidget(self.canvas_G5)

        self.canvas_G6=MplCanvas(self,dpi=100,left=0.0,right=1.,bottom=0.,top=1.)
        self.G6_layout=QVBoxLayout(self.ui.Guide6)
        self.G6_layout.addWidget(self.canvas_G6)



    def logging(self,message):
        self.ui.log.appendPlainText(message)
        self.ui.log_2.appendPlainText(message)

##### Main Functions corresponding to the GUI action #####
    @asyncSlot()
    async def flat_button_clicked(self):
        if self.ui.pushbtn_Flat.isChecked():
            self.ui.pushbtn_Flat.setStyleSheet("color: green; font-weight:900;")
            await handle_lamp('flaton', self.ICS_client)
            self.logging('Sent Flat ON')
#            self.ui.log.appendPlainText('Sent Flat ON')
        else:
            self.ui.pushbtn_Flat.setStyleSheet("color: black;")
            await handle_lamp('flatoff', self.ICS_client)
            self.logging('Sent Flat OFF')
#            self.ui.log.appendPlainText('Sent Flat OFF')

    @asyncSlot()
    async def arc_button_clicked(self):
        if self.ui.pushbtn_Arc.isChecked():
            self.ui.pushbtn_Arc.setStyleSheet("color: green; font-weight:900;")
            await handle_lamp('arcon', self.ICS_client)
            self.ui.log.appendPlainText('Sent Arc ON')
        else:
            self.ui.pushbtn_Arc.setStyleSheet("color: black;")
            await handle_lamp('arcoff', self.ICS_client)
            self.ui.log.appendPlainText('Sent Arc OFF')





    @asyncSlot()
    async def rabbitmq_define(self):
        # Connect RabbitMQ
        with open('./Lib/KSPEC.ini', 'r') as f:
            kspecinfo = json.load(f)

        self.ICS_client = AMQclass(
            kspecinfo['RabbitMQ']['ip_addr'],
            kspecinfo['RabbitMQ']['idname'],
            kspecinfo['RabbitMQ']['pwd'],
            'ICS', 'ics.ex'
        )

        react = await self.ICS_client.connect()
        self.ui.log.appendPlainText(react)
#        self.ui.log_2.appendPlainText(react)
        #self.processlog.append(react)
        react = await self.ICS_client.define_producer()
        self.ui.log.appendPlainText(react)
        await self.ICS_client.define_consumer()
        asyncio.create_task(self.wait_for_response())


    def load_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self)

        if not file_path:
            return

        if file_path:
            with open(file_path,'r') as f:
                lines=f.readlines()

        header = lines[0].strip().split()
        tile_lines = lines[1:]


        dialog = SelectTile(header[:4], tile_lines, self)
        if dialog.exec() == QDialog.Accepted and dialog.selected_values:
            self.select_tile=dialog.selected_values[0]
            self.obsnum=dialog.selected_values[2]
            self.expT=dialog.selected_values[3]


        sciobs=sciobscli()
        filename=os.path.basename(file_path)
        wild=filename.split('_')
        sciobs.project=wild[0]
        sciobs.obsdate=wild[-1].split('.')[0]
        self.project=wild[0]
        self.obsdate=wild[-1].split('.')[0]
        self.tilemsg,self.guidemsg,self.objmsg,self.motionmsg1,self.motionmsg2=sciobs.loadtile(self.select_tile)
        self.ra,self.dec=self.convert_to_sexagesimal(sciobs.ra,sciobs.dec)

        self.ui.lineEdit_TileID.setText(f'{self.select_tile}')
        self.ui.lineEdit_ra_1.setText(f'{self.ra}')
        self.ui.lineEdit_dec_1.setText(f'{self.dec}')
        self.ui.lineEdit_exp_time_1.setText(f'{self.expT}')
        self.ui.lineEdit_n_exp_1.setText(f'{self.obsnum}')


    @asyncSlot()
    async def load_tile(self):
        self.ui.lineEdit_CProj.setText(f'{self.project}')
        self.ui.lineEdit_CTile.setText(f'{self.select_tile}')
        await self.ICS_client.send_message("GFA", self.guidemsg)
        await self.response_queue.get()
        await asyncio.sleep(2)

        await self.ICS_client.send_message("MTL", self.objmsg)
        await self.response_queue.get()
        await asyncio.sleep(2)

        await self.ICS_client.send_message("FBP", self.objmsg)
        await self.response_queue.get()
        await asyncio.sleep(2)

        await self.ICS_client.send_message("FBP", self.motionmsg1)
        await self.response_queue.get()
        await asyncio.sleep(2)

        await self.ICS_client.send_message("FBP", self.motionmsg2)
        await self.response_queue.get()
        await asyncio.sleep(2)


    def autoguiding(self):
        cutimgpath='/media/shyunc/DATA/KSpec/KSPEC_ICS/GFA/kspec_gfa_controller/src/img/cutout/'
        guidenum=['1','2','3','4']
        G_canvas=[self.canvas_G1,self.canvas_G2,self.canvas_G3,self.canvas_G4]

        for i,can in enumerate(G_canvas):
            with fits.open(cutimgpath+'cutout_fluxmax_'+str(i+1)+'.fits') as hdul:
                data=hdul[0].data

            self.G_zmin, self.G_zmax = zs.zscale(data)
            can.imshows(data,vmin=self.G_zmin,vmax=self.G_zmax,cmap='gray',origin='lower')
        


    @asyncSlot()
    async def take_image(self):
        await handle_spec('getobj 3 1', self.ICS_client)
        self.ui.log.appendPlainText("sent message to device 'SPEC'. message: Get 1 bias images.")
        msg=await self.response_queue.get()
#        self.ui.log.appendPlainText(f"{msg['file']}")

        filename=msg['file']

        self.reload_img(filename)


    def reload_img(self,filename):
        rawdir='/media/shyunc/DATA/KSpec/RAWDATA/'
        filepath=os.path.join(rawdir,filename)

        try:
            with fits.open(filepath) as hdul:
                data = hdul[0].data

            # Z-scale 계산
            self.zmin, self.zmax = zs.zscale(data)

            # 기존 캔버스 초기화
            self.canvas_B.imshows(
                data,
                vmin=self.zmin,
                vmax=self.zmax,
                cmap='gray',
                origin='lower'
             )

            self.canvas_R.imshows(
                data,
                vmin=self.zmin,
                vmax=self.zmax,
                cmap='gray',
                origin='lower'
             )

#            self.canvas.ax.axis('off')
#            self.canvas.draw()

            self.ui.log.appendPlainText(f"Loaded image: {filename}")

        except Exception as e:
            print(f"[ERROR] Could not load image {filepath}: {e}")
            self.ui.log.appendPlainText(f"Failed to load image: {e}")
            

    def convert_to_sexagesimal(self,ra_deg, dec_deg):
        """Converts RA and DEC from degrees to sexagesimal format."""
        ra = Angle(ra_deg, unit=u.degree)
        dec = Angle(dec_deg, unit=u.degree)

        ra_hms = ra.to_string(unit=u.hour, sep=':', precision=2, pad=True)
        dec_dms = dec.to_string(unit=u.degree, sep=':', alwayssign=True, precision=2)
        return ra_hms, dec_dms



    async def wait_for_response(self):
        """
        Waits for responses from the K-SPEC sub-system and distributes then appropriately.
        """
        while True:
            try:
                response = await self.ICS_client.receive_message("ICS")
                response_data = json.loads(response)
                inst=response_data['inst']
                message=response_data.get('message','No message')
                self.logging(message)

                if isinstance(message,dict):
                    message = json.dumps(message, indent=2)
                    print(f'\033[94m[ICS] received from {inst}: {message}\033[0m\n', flush=True)
                else:
                    print(f'\033[94m[ICS] received from {inst}: {response_data["message"]}\033[0m\n', flush=True)

                queue_map = {"GFA": self.GFA_response_queue, "ADC": self.ADC_response_queue, "SPEC": self.SPEC_response_queue}
                if response_data['inst'] in queue_map and response_data['process'] == 'ING':
#                    print(f'put in {response_data["inst"]}: {response_data}')
                    await queue_map[response_data['inst']].put(response_data)
#                elif response_data['inst'] == 'SPEC' and response_data['process'] == 'Done':
#                    await self.SPEC_response_queue.put(response_data)
                else:
                    await self.response_queue.put(response_data)
#                    print(f'response_queue formation: {response_data}')
            except Exception as e:
                print(f"Error in wait_for_response: {e}", flush=True)
        

#Close Event : to prevent to close the window easily
    def closeEvent(self, QCloseEvent):
        re = QMessageBox.question(self, "Close the program", "Are you sure you want to quit?",
                    QMessageBox.Yes|QMessageBox.No)

        if re == QMessageBox.Yes:
            QCloseEvent.accept()
        else:
            QCloseEvent.ignore() 

    def timeout(self):
        sender = self.sender()
        currentTime = QDateTime.currentDateTime().toString('yyyy.MM.dd, hh:mm:ss')
        currentutc = QDateTime.currentDateTimeUtc().toString('yyyy.MM.dd, hh:mm:ss')
        #print(currentTime)
        if id(sender) == id(self.timer):
            self.ui.lcd_lt.display(currentTime)
            self.ui.lcd_utc.display(currentutc)

#    def load_data(self, 

if __name__ == "__main__":
    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    window = MainWindow()
    window.show()
    
    with loop:
        loop.run_forever()
#    sys.exit(app.exec())
