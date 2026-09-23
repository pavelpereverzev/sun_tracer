"""
description: Sun position calculator and shadow generation tool.<br>Select a layer, field containig height values (in meters), and the objects themselves to see their shadow silhouettes along with the sun's path.<br>Click <a href="https://github.com/pavelpereverzev/sun_tracer">here</a> for details and instructions.
author: Pavel Pereverzev
author_mail: telegram @PavelPereverzev
"""


from qgis.gui import QgsRubberBand
from qgis.core import *
from qgis._core import *
from qgis.utils import iface

from qgis.PyQt import uic
from qgis.PyQt import QtCore
from qgis.PyQt.QtGui import *
from qgis.PyQt.QtCore import *
from qgis.PyQt.QtWidgets import (QApplication, QStyle, QWidget, QGridLayout, QLabel, QPushButton, QCheckBox, 
    QSpinBox, QComboBox, QMessageBox, QProgressBar, QDateEdit, QTimeEdit, QSlider,
    QMainWindow, QHBoxLayout, QVBoxLayout, QDial, QGroupBox
    )
from qgis.PyQt.QtNetwork import QNetworkAccessManager, QNetworkRequest

import processing
from shapely.geometry import Polygon
from shapely.ops import unary_union
import math
from datetime import datetime, timedelta, timezone
import pytz
import os
import zipfile
import gc

URL_TZ_LAYER = "https://github.com/pavelpereverzev/sun_tracer/raw/refs/heads/main/countries_tz.zip"
COUNTRIES_LAYER_PATH = os.path.join(project_folder, 'countries_tz.gpkg')
COUNTRY_LAYER = None
COUNTRY_INDEX = None

RAD = math.pi / 180
DAY_MS = 86400000
J1970 = 2440588
J2000 = 2451545
E = RAD * 23.4397  

# time config like in suncalc.js
_TIMES = [(-0.833, 'sunrise', 'sunset')]

polygon_layer_style = {
    "border_width_map_unit_scale":"3x:0,0,0,0,0,0",
    "color":"0,0,0,200",
    "joinstyle":"bevel",
    "offset":"0,0",
    "offset_map_unit_scale":"3x:0,0,0,0,0,0",
    "offset_unit":"MM",
    "outline_color":"0,0,0,150",
    "outline_style":"solid",
    "outline_width":"0.26",
    "outline_width_unit":"MM",
    "style":"solid"
}

def get_country_layer():
    # open countries layer and build spatial index

    global COUNTRY_LAYER, COUNTRY_INDEX
    if COUNTRY_LAYER is not None:
        return COUNTRY_LAYER, COUNTRY_INDEX

    if not os.path.exists(COUNTRIES_LAYER_PATH):
        return None, None

    layer = QgsVectorLayer(COUNTRIES_LAYER_PATH, "countries", "ogr")
    if not layer.isValid():
        return None, None

    index = QgsSpatialIndex(layer.getFeatures())
    COUNTRY_LAYER, COUNTRY_INDEX = layer, index
    return COUNTRY_LAYER, COUNTRY_INDEX


def get_tzid_for_latlon(lat, lon):
    # get IANA timezone id (e.g. 'Europe/Berlin') by lat/lon

    layer, index = get_country_layer()
    if layer is None:
        return None

    pnt = QgsGeometry.fromPointXY(QgsPointXY(lon, lat))
    candidate_ids = index.intersects(pnt.boundingBox())
    for fid in candidate_ids:
        feat = layer.getFeature(fid)
        if feat.geometry().contains(pnt):
            iso = feat["tzid"]
            if iso and iso != "-99":
                return iso
    return None


def get_tz_for_latlon(lat, lon):
    # get timezone for lat/lon using pytz and countries layer

    tzid = get_tzid_for_latlon(lat, lon)
    if tzid:
        return pytz.timezone(tzid)

    # if there is no country, get approx timezone by longitude
    return timezone(timedelta(hours=round(lon/15)))


def ring_shadow(coords, dx, dy):
    shifted = [(x+dx, y+dy) for x, y in coords]
    faces = []
    for i in range(len(coords)-1):
        quad = Polygon([
            coords[i],
            coords[i+1],
            shifted[i+1],
            shifted[i]
        ])
        if not quad.is_empty and quad.is_valid:
            faces.append(quad)
    return faces


def polygon_shadow(poly, dx, dy):
    faces = []
    faces.extend(ring_shadow(list(poly.exterior.coords), dx, dy))

    for interior in poly.interiors:
        faces.extend(ring_shadow(list(interior.coords), dx, dy))
    shadow = unary_union(faces)
    shadow = shadow.difference(poly)
    return shadow
    
# suncalc.js implementation

def _to_julian(dt):
    return dt.timestamp() * 1000 / DAY_MS - 0.5 + J1970

def _from_julian(j):
    return datetime.fromtimestamp((j + 0.5 - J1970) * DAY_MS / 1000, tz=timezone.utc)

def _to_days(dt):
    return _to_julian(dt) - J2000

def _right_ascension(l, b):
    return math.atan2(math.sin(l) * math.cos(E) - math.tan(b) * math.sin(E), math.cos(l))

def _declination(l, b):
    return math.asin(math.sin(b) * math.cos(E) + math.cos(b) * math.sin(E) * math.sin(l))

def _azimuth(H, phi, dec):
    return math.atan2(math.sin(H), math.cos(H) * math.sin(phi) - math.tan(dec) * math.cos(phi))

def _altitude(H, phi, dec):
    return math.asin(math.sin(phi) * math.sin(dec) + math.cos(phi) * math.cos(dec) * math.cos(H))

def _sidereal_time(d, lw):
    return RAD * (280.16 + 360.9856235 * d) - lw

def _solar_mean_anomaly(d):
    return RAD * (357.5291 + 0.98560028 * d)

def _ecliptic_longitude(M):
    C = RAD * (1.9148 * math.sin(M) + 0.02 * math.sin(2 * M) + 0.0003 * math.sin(3 * M))
    P = RAD * 102.9372
    return M + C + P + math.pi

def _sun_coords(d):
    M = _solar_mean_anomaly(d)
    L = _ecliptic_longitude(M)
    return _declination(L, 0), _right_ascension(L, 0)  # dec, ra


def sun_position(dt, lat, lon):
    lw, phi = RAD * -lon, RAD * lat
    d = _to_days(dt)
    dec, ra = _sun_coords(d)
    H = _sidereal_time(d, lw) - ra
    return math.degrees(_azimuth(H, phi, dec)) % 360, math.degrees(_altitude(H, phi, dec))


def _hour_angle(h, phi, d):
    denom = math.cos(phi) * math.cos(d)
    if denom == 0:
        # sun is on poles 
        return None
    cos_h = (math.sin(h) - math.sin(phi) * math.sin(d)) / denom
    if cos_h < -1 or cos_h > 1:
        # no sunrise/sunset
        return None
    return math.acos(cos_h)

def _julian_cycle(d, lw):
    return round(d - 0.0009 - lw / (2 * math.pi))

def _approx_transit(Ht, lw, n):
    return 0.0009 + (Ht + lw) / (2 * math.pi) + n

def _solar_transit_j(ds, M, L):
    return J2000 + ds + 0.0053 * math.sin(M) - 0.0069 * math.sin(2 * L)

def sun_times(dt, lat, lon):
    lw, phi = RAD * -lon, RAD * lat
    d = _to_days(dt)
    n = _julian_cycle(d, lw)
    ds = _approx_transit(0, lw, n)
    M = _solar_mean_anomaly(ds)
    L = _ecliptic_longitude(M)
    dec = _declination(L, 0)
    j_noon = _solar_transit_j(ds, M, L)

    target_tz = dt.tzinfo if dt.tzinfo is not None else timezone.utc
    utc_noon = _from_julian(j_noon).astimezone(target_tz)

    angle, rise_name, set_name = _TIMES[0]
    h0 = angle * RAD
    w = _hour_angle(h0, phi, dec)

    if w is None:
        # polar day/night
        _, noon_alt = sun_position(utc_noon, lat, lon)
        is_polar_day = noon_alt > angle
        return None, None, utc_noon, is_polar_day

    a = _approx_transit(w, lw, n)
    j_set = _solar_transit_j(a, M, L)
    j_rise = j_noon - (j_set - j_noon)

    utc_rise = _from_julian(j_rise)
    utc_set = _from_julian(j_set)

    return (
        utc_rise.astimezone(target_tz),
        utc_set.astimezone(target_tz),
        utc_noon,
        None,
    )


def format_utc_offset(dt):
    offset = dt.utcoffset()
    total_minutes = int(offset.total_seconds() // 60)
    sign = '+' if total_minutes >= 0 else '-'
    hh, mm = divmod(abs(total_minutes), 60)
    return "UTC{}{:02d}:{:02d}".format(sign, hh, mm)


def format_rise_set(s_rise, s_set, is_polar_day):
    if s_rise is None or s_set is None:
        if is_polar_day:
            return 'sunrise: none (polar day)', 'sunset: none (polar day)'
        return 'sunrise: none (polar night)', 'sunset: none (polar night)'
    return (
        'sunrise: ~{}'.format(s_rise.strftime("%H:%M")),
        'sunset: ~{}'.format(s_set.strftime("%H:%M")),
    )


def shadow_length(building_height, sun_altitude_deg):
    # shadow length, m
    if sun_altitude_deg <= 0:
        return None
    return building_height / math.tan(math.radians(sun_altitude_deg))


def shadow_vector(dt, lat, lon, building_height):
    # azimuth/height of the Sun, azimuth and shadow lendth, dx/dy shifts, sunset-sunrise
    azimuth, altitude = sun_position(dt, lat, lon)
    sun_rise, sun_set, sun_noon, is_polar_day = sun_times(dt, lat, lon)

    if sun_rise is not None and sun_set is not None:
        sun_rise_azimuth, sun_rise_alt = sun_position(sun_rise, lat, lon)
        sun_set_azimuth, sun_set_alt = sun_position(sun_set, lat, lon)
    else:
        # polar day/night
        sun_rise_azimuth, sun_rise_alt = azimuth, altitude
        sun_set_azimuth, sun_set_alt = azimuth, altitude

    length = shadow_length(building_height, altitude)

    result = {'sun_azimuth': azimuth, 'sun_altitude': altitude,
              "sun_rise": sun_rise, "sun_set": sun_set, "sun_noon": sun_noon,
              "sun_rise_azimuth": sun_rise_azimuth, "sun_set_azimuth": sun_set_azimuth,
              "is_polar_day": is_polar_day}
    if length is None:
        result.update({'shadow_azimuth': None, 'shadow_length': None, 'dx': None, 'dy': None})
        return result
    shadow_azimuth = (azimuth + 180) % 360
    dx = length * math.sin(math.radians(shadow_azimuth))
    dy = length * math.cos(math.radians(shadow_azimuth))
    result.update({'shadow_azimuth': shadow_azimuth, 'shadow_length': length, 'dx': dx, 'dy': dy})
    return result


def get_sun_pos(dt_obj):
    crs_current = QgsProject.instance().crs()
    crs_4326 = QgsCoordinateReferenceSystem(4326)
    crs_transform_project_to_4326 = QgsCoordinateTransform(crs_current, crs_4326, QgsProject.instance())

    canvas = iface.mapCanvas()
    scale = canvas.scale()
    canvas_hgt = canvas.extent().height()
    canvas_wdt = canvas.extent().width()
    radius_hgt = 0.95 * (canvas_hgt/2)
    radius_wdt = 0.95 * (canvas_wdt/2)

    center_pnt = canvas.center()
    geom_pnt_center = QgsGeometry.fromPointXY(center_pnt)
    geom_pnt_center_orig = QgsGeometry.fromPointXY(center_pnt)
    geom_pnt_center.transform(crs_transform_project_to_4326)
    geom_pnt_center_pnt = geom_pnt_center.asPoint()

    y_shift = abs(geom_pnt_center.asPoint().y())/100

    result_center = shadow_vector(dt_obj, geom_pnt_center_pnt.y(), geom_pnt_center_pnt.x(), 5)
        
    sun_angle_center = 360-(result_center['sun_azimuth']+90 )
    sun_angle_rise = 360-(result_center['sun_rise_azimuth']+90 )
    sun_angle_set = 360-(result_center['sun_set_azimuth']+90 )
    
    shadow_azimuth_center = sun_angle_center

    dx_sun = radius_wdt * math.cos(math.radians(shadow_azimuth_center))
    dy_sun = radius_hgt * math.sin(math.radians(shadow_azimuth_center))

    dx_sun_rise = radius_wdt * math.cos(math.radians(sun_angle_rise))
    dy_sun_rise = radius_hgt * math.sin(math.radians(sun_angle_rise))
    
    dx_sun_set = radius_wdt * math.cos(math.radians(sun_angle_set))
    dy_sun_set = radius_hgt * math.sin(math.radians(sun_angle_set))

    multiplier = -1 if geom_pnt_center.asPoint().y()>0 else 1

    sun_loc_x = center_pnt.x()+dx_sun
    sun_loc_y = center_pnt.y()+dy_sun* y_shift

    sun_rise_loc_x = center_pnt.x()+dx_sun_rise
    sun_rise_loc_y = center_pnt.y()+dy_sun_rise* y_shift

    sun_set_loc_x = center_pnt.x()+dx_sun_set
    sun_set_loc_y = center_pnt.y()+dy_sun_set* y_shift

    point_sun = QgsGeometry.fromPointXY(QgsPointXY(sun_loc_x, sun_loc_y))
    buffer_sun = point_sun.buffer(radius_hgt*0.1, 5)

    point_sun_rise = QgsGeometry.fromPointXY(QgsPointXY(sun_rise_loc_x, sun_rise_loc_y))
    buffer_sun_rise = point_sun_rise.buffer(radius_hgt*0.05, 5)

    point_sun_set = QgsGeometry.fromPointXY(QgsPointXY(sun_set_loc_x, sun_set_loc_y))
    buffer_sun_set = point_sun_set.buffer(radius_hgt*0.05, 5)

    

    shape_cut = [
        QgsPointXY(center_pnt.x(), center_pnt.y()),
        QgsPointXY(sun_rise_loc_x, sun_rise_loc_y),
        QgsPointXY(sun_rise_loc_x+canvas_wdt, sun_rise_loc_y),
        QgsPointXY(sun_rise_loc_x+canvas_wdt, sun_rise_loc_y+canvas_hgt*multiplier),
        QgsPointXY(sun_set_loc_x-canvas_wdt, sun_set_loc_y+canvas_hgt*multiplier),
        QgsPointXY(sun_set_loc_x-canvas_wdt, sun_set_loc_y),
        QgsPointXY(sun_set_loc_x, sun_set_loc_y),
        QgsPointXY(center_pnt.x(), center_pnt.y()),
    ]
    cutter = QgsGeometry().fromPolygonXY([shape_cut])
    

    ellipse_poly = QgsEllipse(
        QgsPoint(center_pnt), 
        radius_hgt * y_shift,
        radius_wdt, 
        # radius_hgt * (abs(geom_pnt_center.asPoint().y())/100 ),
        0.0
    )
    ellipse_line = QgsGeometry(ellipse_poly.toLineString())
    ring_f = ellipse_line.buffer(radius_hgt*0.01, 2)
    ring_rise = ring_f.intersection(cutter)
    ring_set = ring_f.difference(cutter).difference(buffer_sun_set).difference(buffer_sun_rise)
    
    buffer_sun = QgsGeometry.unaryUnion([buffer_sun, ring_rise, buffer_sun_rise, buffer_sun_set])
    return buffer_sun, ring_set, result_center['sun_rise'], result_center['sun_set'], result_center['is_polar_day']



def get_shadows(f_list,  field_name, dt_obj, layer_crs):
    crs_current = QgsProject.instance().crs()
    crs_4326 = QgsCoordinateReferenceSystem(4326)

    crs_transform_4326 = QgsCoordinateTransform(layer_crs, crs_4326, QgsProject.instance())
    crs_transform_project_to_4326 = QgsCoordinateTransform(crs_current, crs_4326, QgsProject.instance())
    crs_transform_project = QgsCoordinateTransform(layer_crs, crs_current, QgsProject.instance())
    out_list = []

    
    dict_another = {}
    for f_orig in f_list:
        dict_another[f_orig.id()] = [[tre.geometry(), tre[field_name]] for tre in f_list if tre.id()!= f_orig.id()]

    for f in f_list:
        feature_geoms = []
        f_hgt = f[field_name]
        
        if type(f_hgt) not in [int, float]:
            try:
                f_hgt = int(f_hgt)
            except:
                f_hgt = 10
        # print(f_hgt)
        geom = f.geometry()
        centroid = geom.centroid()
        centroid.transform(crs_transform_4326)
        centroid_pnt = centroid.asPoint()
        lat = centroid_pnt.y()
        lon = centroid_pnt.x()
        
        result = shadow_vector(dt_obj, lat, lon, f_hgt)
        shadow_hgt = result['shadow_length']
        sun_angle = result['shadow_azimuth'] 

        if not sun_angle:
            continue
        shadow_azimuth = 180-(sun_angle +90)
        shadow_length = result['shadow_length']
        
        polys = geom.asMultiPolygon() if geom.isMultipart() else [geom.asPolygon()]
        new_f = f
        for p in polys:
            exterior = p[0]
            holes = p[1:]
            shp = Polygon(exterior, holes)
            dx = shadow_length * math.cos(math.radians(shadow_azimuth+180))
            dy = shadow_length * math.sin(math.radians(shadow_azimuth+180))
            shadow = polygon_shadow(shp, dx, dy)
            if not shadow.is_empty:
                gg = QgsGeometry.fromWkt(shadow.wkt)
                feature_geoms.append(gg)
        complex_geom = QgsGeometry.unaryUnion(feature_geoms)

        for f_p in dict_another[f.id()]:
            f_an_hgt = f_p[1]
            f_an_geom = f_p[0]

            if type(f_an_hgt) not in [int, float]:
                try:
                    f_an_hgt = int(f_an_hgt)
                except:
                    f_an_hgt = 10
            if f_an_hgt>=f_hgt and f_an_geom.intersects(complex_geom):
                copy_orig = QgsGeometry(f_an_geom)
                copy_shadow = QgsGeometry(complex_geom)
                complex_geom = copy_shadow.difference(copy_orig)
        
        complex_geom = complex_geom.buffer(
            0.5, 2, endCapStyle=QgsGeometry.CapFlat, 
            joinStyle = QgsGeometry.JoinStyleMiter, 
            miterLimit= 2.0
        )
        complex_geom = complex_geom.buffer(
            -0.5, 2, endCapStyle=QgsGeometry.CapFlat, 
            joinStyle = QgsGeometry.JoinStyleMiter, 
            miterLimit= 2.0
        )
        if complex_geom.wkbType()==7:
            complex_geom = QgsGeometry.unaryUnion([g for g in complex_geom.asGeometryCollection() if g.wkbType() in [3, 6] ])

        
        new_f.setGeometry(complex_geom)
        out_list.append(new_f)
        
    return out_list


class SunTracerMW(QMainWindow):
    def __init__(self, parent=None):
        QMainWindow.__init__(self, parent=iface.mainWindow())
        self.setWindowFlags(self.windowFlags() & ~ QtCore.Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)

        self.central_widget = SunTracer(self)
        self.setWindowTitle('Sun Tracer')
        self.resize(400, 100)
        self.setCentralWidget(self.central_widget)
        (script_name:=globals().get("script_name")) and hasattr(iface,"kolba_plugin") and iface.kolba_plugin.__setitem__(script_name, self) # - where widget is shown
        self.show()
    
    def closeEvent(self, event):
        global COUNTRY_LAYER

        (script_name:=globals().get("script_name")) and hasattr(iface,"kolba_plugin") and iface.kolba_plugin.__setitem__(script_name, None) # - where widget is closing, i.e. closeEvent function
        self.central_widget.rb_shadow.reset()
        self.central_widget.rb_sun.reset()
        self.central_widget.rb_night.reset()

        if COUNTRY_LAYER:
            QgsProject.instance().removeMapLayer(COUNTRY_LAYER.id())
            COUNTRY_LAYER = None
            COUNTRY_INDEX = None
        
        gc.collect()

        try:
            iface.mapCanvas().selectionChanged.disconnect(self.central_widget.draw_shape)
        except Exception as e:
            print(e)

        try:
            iface.mapCanvas().currentLayerChanged.disconnect(self.central_widget.draw_shape)
        except Exception as e:
            print(e)


class LabeledTimeSlider(QSlider):
    def paintEvent(self, event):
        super().paintEvent(event)
        
        painter = QPainter(self)
        painter.setFont(QFont("Arial", 9))
        painter.setPen(Qt.GlobalColor.darkGray)

        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        available_width = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, opt, QStyle.SubControl.SC_SliderGroove, self
        ).width()
        
        handle_rect = self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, opt, QStyle.SubControl.SC_SliderHandle, self
        )
        offset = handle_rect.width() // 2

        for hour in range(24):
            value = hour * 60
            x = QStyle.sliderPositionFromValue(
                self.minimum(), self.maximum(), value, available_width
            ) + offset
            
            text = str(hour)
            text_width = painter.fontMetrics().horizontalAdvance(text)
            text_x = x - (text_width // 2)
            text_y = self.height() - 2
            
            painter.drawText(text_x, text_y, text)
            
        painter.end()

class SunTracer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setGeometry(500, 500, 200, 10)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowType.WindowStaysOnTopHint)

        # init anchor_utc, will be set later based on user input or map center
        self.anchor_utc = None

        # get the center of the map canvas in lat/lon and determine the timezone for this location
        # also fix current UTC time
        init_lat, init_lon = self.get_canvas_center_latlon()
        init_tz = get_tz_for_latlon(init_lat, init_lon)
        self.anchor_utc = datetime.now(timezone.utc)
        init_local = self.anchor_utc.astimezone(init_tz)

        # rubberbands
        self.rb_night = QgsRubberBand(iface.mapCanvas(), QgsWkbTypes.PolygonGeometry)
        self.rb_night.setColor(QColor(0,0,0,150))
        self.rb_night.setWidth(2)
        self.rb_night.reset()
        
        self.rb_shadow = QgsRubberBand(iface.mapCanvas(), QgsWkbTypes.PolygonGeometry)
        self.rb_shadow.setColor(QColor(155,10,100,150))
        self.rb_shadow.setWidth(2)
        self.rb_shadow.reset()

        self.rb_sun = QgsRubberBand(iface.mapCanvas(), QgsWkbTypes.PolygonGeometry)
        self.rb_sun.setColor(QColor(255,100,0,150))
        self.rb_sun.setWidth(2)
        self.rb_sun.reset()

        # layouts
        layout = QVBoxLayout(self)
        gb_sun = QGroupBox("Sun settings")
        gb_layer = QGroupBox("Shadow generator")

        lt_sun = QVBoxLayout()
        gb_sun.setLayout(lt_sun)

        lt_layer = QVBoxLayout()
        gb_layer.setLayout(lt_layer)

        # sun settings
        # 1. preview
        self.preview = QCheckBox("Show path of the sun")
        self.preview.setChecked(True)

        # 2. date
        self.lbl_date = QLabel("Date:")
        self.date_picker = QDateEdit()
        self.date_picker.setCalendarPopup(True)
        self.date_picker.setDisplayFormat("dd.MM.yyyy") 
        # self.date_picker.setDisplayFormat("yyyy.MM.dd") 

        # 3. time
        self.lbl_time = QLabel("Time:")
        self.time_picker = QTimeEdit()
        self.time_picker.setDisplayFormat("HH:mm")

        # 3.1 time picker
        grid_layout = QGridLayout()
        grid_layout.setSpacing(0) 

        self.slider = QSlider(Qt.Orientation.Horizontal, self)
        self.slider.setMinimum(0)
        self.slider.setMaximum(1440)  
        self.slider.setTickInterval(60)
        self.slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        grid_layout.addWidget(self.slider, 0, 0, 1, 24)

        for hour in range(24):
            lbl = QLabel(str(hour) if hour < 24 else "24", self)
            lbl.setStyleSheet("font-size: 10px; color: #555555; font-family: Arial;")
            grid_layout.setColumnStretch(hour, 1)
            grid_layout.addWidget(lbl, 1, hour, alignment=Qt.AlignmentFlag.AlignLeft)
        
        self.slider.setSingleStep(1)
        self.slider.setPageStep(15)

        # layer settings
        # 1. layer selector
        self.lbl_layer_selector = QLabel("Layer:")
        self.layer_selector = QComboBox()

        # 2. field selector
        self.lbl_hgt_field = QLabel("Heights field:")
        self.hgt_field = QComboBox()
        
        # 3. create options
        self.diff = QCheckBox("Dissolve intersecting shadows")
        self.diff.setChecked(True)
        self.btn_create_layer = QPushButton("Create layer")

        # layout completition    
        lt_sun.addWidget(self.lbl_date)
        lt_sun.addWidget(self.date_picker)
        lt_sun.addWidget(self.lbl_time)
        lt_sun.addWidget(self.time_picker)
        lt_sun.addLayout(grid_layout)
        lt_sun.addWidget(self.preview)

        lt_layer.addWidget(self.lbl_layer_selector)
        lt_layer.addWidget(self.layer_selector)
        lt_layer.addWidget(self.lbl_hgt_field)
        lt_layer.addWidget(self.hgt_field)
        lt_layer.addWidget(self.diff)
        lt_layer.addWidget(self.btn_create_layer)

        layout.addWidget(gb_sun)
        layout.addWidget(gb_layer)

        self.setLayout(layout)

        # silent slider set
        self.slider.blockSignals(True)
        qtime_obj = self.time_picker.time()
        total_minutes = qtime_obj.hour() * 60 + qtime_obj.minute()
        self.slider.setValue(total_minutes)
        self.slider.blockSignals(False)

        # silent layer/date/time set
        self.layer_selector.blockSignals(True)
        self.hgt_field.blockSignals(True)
        self.date_picker.blockSignals(True)
        self.time_picker.blockSignals(True)
        
        self.date_picker.setDate(QDate(init_local.year, init_local.month, init_local.day))
        self.time_picker.setTime(QTime(init_local.hour, init_local.minute))

        self.layer_selector.blockSignals(False)
        self.hgt_field.blockSignals(False)
        self.date_picker.blockSignals(False)
        self.time_picker.blockSignals(False)

        # signals connection 
        self.btn_create_layer.clicked.connect(self.create_layer)
        self.layer_selector.activated.connect(self.get_fields)
        self.hgt_field.activated.connect(self.draw_shape)
        self.date_picker.dateChanged.connect(self.draw_shape)
        self.time_picker.timeChanged.connect(self.update_time)
        self.slider.valueChanged.connect(self.update_time)
        self.preview.stateChanged.connect(self.upd_sun_trace)

        iface.mapCanvas().selectionChanged.connect(self.draw_shape)
        iface.mapCanvas().currentLayerChanged.connect(self.draw_shape)
        iface.mapCanvas().extentsChanged.connect(self.upd_sun_trace)

        self.add_layers()
        self.get_fields()
        
        index = self.layer_selector.findData(iface.activeLayer())
        if index!=-1:
            self.layer_selector.setCurrentIndex(index)
            # self.get_fields()

        
        self.layer_selector.setFocus()
        # pre-run 
        self.upd_sun_trace()
        self.show()

    def get_fields(self):
        self.hgt_field.clear()
        current_layer = self.layer_selector.currentData()
        if not current_layer:
            return
        fields = [f for f in current_layer.fields().names()]
        for field in fields:
            self.hgt_field.addItem(field, userData=field)
        self.draw_shape()

    
    def get_canvas_center_latlon(self):
        canvas = iface.mapCanvas()
        crs_current = QgsProject.instance().crs()
        crs_4326 = QgsCoordinateReferenceSystem(4326)
        trs = QgsCoordinateTransform(crs_current, crs_4326, QgsProject.instance())
        center_pnt = canvas.center()
        geom = QgsGeometry.fromPointXY(center_pnt)
        geom.transform(trs)
        pnt = geom.asPoint()
        return pnt.y(), pnt.x()  # lat, lon

    def update_datetime_object(self, lat=None, lon=None):
        q_date = self.date_picker.date()
        q_time = self.time_picker.time()

        if lat is None or lon is None:
            lat, lon = self.get_canvas_center_latlon()

        tz = get_tz_for_latlon(lat, lon)

        naive_dt = datetime(
            year=q_date.year(),
            month=q_date.month(),
            day=q_date.day(),
            hour=q_time.hour(),
            minute=q_time.minute()
            # tzinfo=tz
        )
        if hasattr(tz, "localize"):
            dt_object = tz.localize(naive_dt)
        else:
            dt_object = naive_dt.replace(tzinfo=tz)

        # change anchor_utc to the UTC equivalent of the local time at the new lat/lon
        self.anchor_utc = dt_object.astimezone(timezone.utc)
        return dt_object

    def update_time(self):
        sender = self.sender()
        if sender ==  self.time_picker:
            self.slider.blockSignals(True)
            qtime_obj = self.time_picker.time()
            total_minutes = qtime_obj.hour() * 60 + qtime_obj.minute()
            self.slider.setValue(total_minutes)
            
            self.slider.blockSignals(False)
        
        if sender ==  self.slider: 
            self.time_picker.blockSignals(True)
            total_minutes = self.slider.value()
            hours = total_minutes // 60
            minutes = total_minutes % 60
            qtime_obj = QTime(hours, minutes)
            self.time_picker.setTime(qtime_obj)

            self.time_picker.blockSignals(False)
        self.draw_shape()

    def upd_sun_trace(self):
        if self.preview.isChecked():
            lat, lon = self.get_canvas_center_latlon()
            tz = get_tz_for_latlon(lat, lon)
            if self.anchor_utc is None:
                self.anchor_utc = datetime.now(timezone.utc)

            # convert anchor_utc to local time at the new lat/lon
            dt_obj = self.anchor_utc.astimezone(tz)
            dt_utc = datetime.now(timezone.utc)

            self.date_picker.blockSignals(True)
            self.time_picker.blockSignals(True)
            self.slider.blockSignals(True)

            self.date_picker.setDate(QDate(dt_obj.year, dt_obj.month, dt_obj.day))
            self.time_picker.setTime(QTime(dt_obj.hour, dt_obj.minute))
            self.slider.setValue(dt_obj.hour * 60 + dt_obj.minute)

            self.slider.blockSignals(False)
            self.time_picker.blockSignals(False)
            self.date_picker.blockSignals(False)

            night_geom = None
            sun_geom = None
    
            sun_geom, night_geom, s_rise, s_set, is_polar_day = get_sun_pos(dt_obj)
            s_rise_str, s_set_str = format_rise_set(s_rise, s_set, is_polar_day)
            self.lbl_time.setText("Time ({}, {}, {}):".format(format_utc_offset(dt_obj), s_rise_str, s_set_str))
            if night_geom:
                self.rb_night.setToGeometry(night_geom)
            if sun_geom:
                self.rb_sun.setToGeometry(sun_geom)
        else:
            self.rb_night.reset()
            self.rb_sun.reset()
 
    
    def draw_shape(self):
        # print(self.sender().text())
        if not self.preview.isChecked():
            return
        
        dt_utc = datetime.now(timezone.utc)

        self.rb_shadow.reset()
        self.rb_sun.reset()
        self.rb_night.reset()
        
        current_layer = self.layer_selector.currentData()
        current_field = self.hgt_field.currentData()

        if current_layer and current_field:
            request = QgsFeatureRequest().setSubsetOfAttributes([current_field], current_layer.fields())
        else:
            request = QgsFeatureRequest()

        
        if current_layer:
            layer_crs = current_layer.crs()
            selection = list(current_layer.getSelectedFeatures(request))
        else:
            layer_crs = QgsProject.instance().crs()
            selection = []
        project_crs = QgsProject.instance().crs()
        trs = QgsCoordinateTransform(layer_crs, project_crs, QgsProject.instance())
        
        shadows_feature = []
        dt_obj = self.update_datetime_object()
        night_geom = None
        sun_geom = None

        sun_geom, night_geom, s_rise, s_set, is_polar_day = get_sun_pos(dt_obj)
        s_rise_str, s_set_str = format_rise_set(s_rise, s_set, is_polar_day)

        self.lbl_time.setText("Time ({}, {}, {}):".format(format_utc_offset(dt_obj), s_rise_str, s_set_str))
        if selection:
            shadows_feature = get_shadows(selection[:20], current_field, dt_obj, layer_crs)

        if shadows_feature:
            geoms = [f.geometry() for f in shadows_feature if f.geometry().wkbType() in [3,6] ]
            
            standardized_geoms = []
            for g in geoms:
                g = g.makeValid()
                if not g.isMultipart():
                    standardized_geoms.append(QgsGeometry.fromMultiPolygonXY([g.asPolygon()]))
                else:
                    standardized_geoms.append(g)
            complex_geom = QgsGeometry.unaryUnion(standardized_geoms)

            complex_geom = complex_geom.buffer(
                0.5, 2, endCapStyle=QgsGeometry.CapFlat, 
                joinStyle = QgsGeometry.JoinStyleMiter, 
                miterLimit= 2.0
            )
            complex_geom = complex_geom.buffer(
                -0.5, 2, endCapStyle=QgsGeometry.CapFlat, 
                joinStyle = QgsGeometry.JoinStyleMiter, 
                miterLimit= 2.0
            )

            complex_geom.transform(trs)
            complex_geom = complex_geom.makeValid()
            if complex_geom.wkbType()==7:
                complex_geom = QgsGeometry.unaryUnion([g for g in complex_geom.asGeometryCollection() if g.wkbType() in [3, 6] ])
                
            self.rb_shadow.setToGeometry(complex_geom)
        if night_geom:
            self.rb_night.setToGeometry(night_geom)
        if sun_geom:
            self.rb_sun.setToGeometry(sun_geom)
            
    
    def create_layer(self):
        current_layer = self.layer_selector.currentData()
        current_field = self.hgt_field.currentData()
        

        if not current_layer:
            self.show_message("Add vector layer containing polygon features with heights data")
            return
        
        if not current_field:
            self.show_message("Add heights field to layer")
            return

        request = QgsFeatureRequest().setSubsetOfAttributes([current_field], current_layer.fields())

        selection = list(current_layer.getSelectedFeatures(request))
        if not selection or not self.rb_shadow.asGeometry():
            self.show_message("Select objects to get shadows layer")
            return

        dt_obj = self.update_datetime_object()
        shadows_feature = get_shadows(selection, self.hgt_field.currentData(), dt_obj, current_layer.crs())

        layer_gen = current_layer.materialize(QgsFeatureRequest().setFilterFids([]))
       
        extent_shadows = QgsGeometry.unaryUnion([sh.geometry() for sh in shadows_feature]).boundingBox()
        temp_selection_layer = current_layer.materialize(
            QgsFeatureRequest().setFilterRect(extent_shadows)
        )

        layer_gen.setCrs(current_layer.crs())
        layer_gen.dataProvider().addFeatures(shadows_feature)
        fill_symbol = QgsFillSymbol.createSimple(polygon_layer_style)
        renderer = QgsSingleSymbolRenderer(fill_symbol)
        if self.diff.isChecked():
            fixed_source = processing.run(
                "native:fixgeometries", {
                    'INPUT':temp_selection_layer,
                    'METHOD':1,
                    'OUTPUT':'TEMPORARY_OUTPUT'}
                )['OUTPUT']
            fixed_shadows = processing.run(
                "native:fixgeometries", {
                    'INPUT':layer_gen,
                    'METHOD':1,
                    'OUTPUT':'TEMPORARY_OUTPUT'}
                )['OUTPUT']
            differ_layer = processing.run(
                "native:dissolve", {
                    'INPUT':fixed_shadows,
                    'FIELD':[],
                    'SEPARATE_DISJOINT':True ,
                    'OUTPUT':'TEMPORARY_OUTPUT'})['OUTPUT']
            differ_layer.setName(f"{current_layer.name()}_shadows")
            differ_layer.setRenderer(renderer)
            QgsProject.instance().addMapLayer(differ_layer)
        else:
            layer_gen.setRenderer(renderer)
            layer_gen.setName(f"{current_layer.name()}_shadows")
            QgsProject.instance().addMapLayer(layer_gen)
            
    
    def add_layers(self):
        for layer in QgsProject.instance().mapLayers().values():
            if type(layer) == QgsVectorLayer and layer.isValid() and layer.geometryType() == QgsWkbTypes.PolygonGeometry:
                self.layer_selector.addItem(layer.name(), userData=layer)
    
    def show_message(self, txt):
        msg = QMessageBox()
        msg.warning(self, "Notificaion", txt)


class Downloader(QMainWindow):
    def __init__(self):
        super().__init__(parent=iface.mainWindow())
        self.setWindowFlags(self.windowFlags() & ~QtCore.Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        # widgets
        self.setWindowTitle("sun_stacer files checker")
        centralWidget = QWidget()
        self.layout = QVBoxLayout()
        self.h_layout = QHBoxLayout()
        files_list_check = [
            "countries_tz.zip"
        ]
        url_files = '<br>'.join(['<a href="{}">countries_tz.zip</a>'.format(URL_TZ_LAYER)])
        label = QLabel(
            f"""
            Plugin requires additional file for working:<br>
            {url_files}<br>
            It will be saved here:<br>
            {os.path.normpath(project_folder)}<br><br>
            Proceed to download?
            """)
        label.setOpenExternalLinks(True)
        label.setTextFormat(Qt.TextFormat.RichText)

        self.yes_btn = QPushButton("Download")
        self.cancel_btn = QPushButton("Stop")
        self.cancel_btn.setDisabled(True)
        self.pr_bar = QProgressBar()
        self.pr_bar.setDisabled(True)

        # self.h_layout.addWidget(self.cancel_btn)
        self.h_layout.addWidget(self.yes_btn)
        
        self.layout.addWidget(label)
        self.layout.addLayout(self.h_layout)
        self.layout.addWidget(self.pr_bar)
        self.layout.setStretch(1, 1)

        centralWidget.setLayout(self.layout)
        self.setCentralWidget(centralWidget)

        self.show()

        self.manager = QNetworkAccessManager(self)
        self.yes_btn.clicked.connect(self.start_download)
        self.cancel_btn.clicked.connect(self.stop_download)

    def stop_download(self):
        if self.reply and self.reply.isRunning():
            self.reply.abort()
            self.pr_bar.setValue(0)
            self.yes_btn.setText("Download")
            
    def warning_message(self, err_text):
        msg = QMessageBox()
        msg.warning(self, "Notification", err_text)
        return

    def start_download(self):
        if self.yes_btn.text() == "Stop loading":
            self.stop_download()
            return
        else:
            self.yes_btn.setText("Stop loading")
            url = QUrl(URL_TZ_LAYER)
            request = QNetworkRequest(url)
            request.setAttribute(
                QNetworkRequest.Attribute.RedirectPolicyAttribute,
                QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
            )
            self.reply = self.manager.get(request)
            self.reply.downloadProgress.connect(self.update_progress)
            self.reply.finished.connect(self.save_file)

    def update_progress(self, bytes_received, bytes_total):
        if bytes_total > 0:
            self.pr_bar.setMaximum(bytes_total)
            self.pr_bar.setValue(bytes_received)

    def save_file(self):
        tzip_file = os.path.join(project_folder, "countries_tz.zip")
        data = self.reply.readAll()
        if data.isEmpty():
            return
        with open(tzip_file, "wb") as f:
            f.write(data)
        self.yes_btn.setText("Ready!")
        self.cancel_btn.setDisabled(True)
        
        self.pr_bar.setFormat("Unpacking layer...")
        QApplication.processEvents()
        
        try:
            with zipfile.ZipFile(tzip_file, 'r') as zip_ref:
                zip_ref.extractall(project_folder)
            app = SunTracerMW()
            self.close()
        except Exception as e:
            self.warning_message(e, "Error unpacking layer")
            return 

            


layer, index = get_country_layer()
if not layer:
    app_check = Downloader()
else:
    app = SunTracerMW()