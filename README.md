# Sun Tracer

Sun Tracer is a tool for viewing the sun's position at a specific time and date, and generating shadows cast by layer objects. Particulary based on [suncalc.js](https://suncalc.net/scripts/suncalc.js)

<img width="1351" height="777" alt="st_img" src="https://github.com/user-attachments/assets/c45a50ca-4b1a-4c18-8544-a8cc068da760" />

It may be useful for architects and urban planners who need to see how building shadows move throughout the day and for insolation analysis in general.

The tool can be installed from the [Kolba plugin](https://github.com/pavelpereverzev/kolba) using the [Web Scripts](https://github.com/pavelpereverzev/kolba#web-scripts) feature: open Kolba, click the WebScripts <img src="https://gisworks.ru/qgis_tools/img/line_webscript.png" height="20" style="vertical-align: middle;"> button, and download the `sun_tracer` script. 

<img width="1272" height="601" alt="install_st" src="https://github.com/user-attachments/assets/266acbf6-a149-424c-b492-14b807292a40" />

>[!NOTE]
>On first launch, the tool will ask you to download the `countries_tz` layer, which is required for timezone detection. You can also download this layer manually from this repository (file [countries.zip](https://github.com/pavelpereverzev/sun_tracer/raw/refs/heads/main/countries_tz.zip)) and unpack it into the folder containing the script.

The tool consists of two sections: **Sun settings** and **Shadow generator**.

### **Sun settings** 
Visualizes the sun's path according to the selected time and date.

<img width="1279" height="434" alt="st_first_new" src="https://github.com/user-attachments/assets/51513452-4648-4cca-845b-656b04ca745c" />



By default, the tool shows the sun's position at the current real moment for whatever location is at the center of the map. When you pan the map to a new location, that same real moment is re-projected into the new location's local time: the sun's position, its path, and the sunrise/sunset labels update accordingly. The time slider and date picker let you set a different time manually, which then becomes the reference moment used when panning further.

`Reset date/time` button will reset date and time values to current ones.

### Shadow generator
Creates a shadow polygon layer from features of an existing layer.

<img width="1279" height="434" alt="st_second (1)" src="https://github.com/user-attachments/assets/b22dec11-42d9-43ea-9e76-58721e6d526a" />



Layer requirements:
* polygon geometry
* coordinate reference system (CRS) should use meters as units — UTM zones or a local CRS are the best options (`EPSG:3857` is not a good choice, since its units are not true meters at most locations on Earth)
* field contiaining objects' heights in meters

To generate shadows, follow these steps:

1. Select a polygon layer from the current project in `Layer` combobox.
2. Select field containing heights (in meters) from `Heights field` combobox.
3. Select the objects you want to check for shadows. As soon as objects are selected, purple shadow geometries appear as a preview (***limited to the first 20 selected objects, just to keep the preview responsive***).
4. If the preview looks right, click `Create layer`. It runs the shadow generation for all selected features, not just the previewed ones.

Other tips:
* Checking `Dissolve intersecting shadows` merges overlapping shadow polygons in the output layer. If unchecked, each shadow remains a separate polygon.
* When calculating shadows, the height and relative positioning of objects are taken into account. If two buildings stand side by side, a shorter building would not cast a shadow onto a taller one if it is situated further away from the sun (relative to the direction of the sun's rays).

Video preview:

https://github.com/user-attachments/assets/6b2fbe44-bac7-48db-99b1-73ad63b6ff81
