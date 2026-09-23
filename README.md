# Sun Tracer

Sun Tracer is a tool for viewing the sun's position at a specific time and date, and generating shadows cast by layer objects. Particulary based on [suncalc.js](https://suncalc.net/scripts/suncalc.js)

It may be useful for architects and urban planners who need to see how building shadows move throughout the day and for insolation analysis in general.

The tool can be installed from the [Kolba plugin](https://github.com/pavelpereverzev/kolba) using the [Web Scripts](https://github.com/pavelpereverzev/kolba#web-scripts) feature: open Kolba, click the WebScripts <img src="[https://xn--80akhbydhr.com](https://camo.githubusercontent.com/ad7b606919a2bc4ef55c6f24e61eb33677686715d4d7d36193338d293e2523cb/68747470733a2f2f676973776f726b732e72752f716769735f746f6f6c732f696d672f6c696e655f7765627363726970742e706e67)" height="20" style="vertical-align: middle;"> button, and download the `sun_tracer` script. On first launch, the tool will prompt you to download the countries/timezones layer, which is required for timezone detection. You can also download this layer manually from this repository (file [countries.zip](https://github.com/pavelpereverzev/sun_tracer/raw/refs/heads/main/countries_tz.zip)) and unpack it into the folder containing the script.

The tool consists of two sections: **Sun settings** and **Shadow generator**.

**Sun settings** visualizes the sun's path according to the selected time and date. 

By default, the tool shows the sun's position at the current real moment for whatever location is at the center of the map. When you pan the map to a new location, that same real moment is re-projected into the new location's local time: the sun's position, its path, and the sunrise/sunset labels update accordingly. The time slider and date picker let you set a different time manually, which then becomes the reference moment used when panning further.

`Reset` button will reset time and date values to current ones.

**Shadow generator** creates a shadow polygon layer from features of an existing layer.

Layer requirements:
* polygon geometry
* coordinate reference system (CRS) should use meters as units — UTM zones or a local CRS are the best options (`EPSG:3857` is not a good choice, since its units are not true meters at most locations on Earth)
* field contiaining objects' heights in meters

Firstly select a polygon layer from the current project in `Layer` combobox. The second combobox named `Heights field` lists the fields of the selected layer. Choose the one that holds the objects' height values in meters.

Next, select the objects you want to analyze. As soon as objects are selected, purple shadow geometries appear as a preview (limited to the first 20 selected objects, just to keep the preview responsive). If the preview looks right, click `Create layer`. It runs the shadow generation for all selected features, not just the previewed ones.

Checking `Dissolve intersecting shadows` merges overlapping shadow polygons in the output layer. If unchecked, each shadow remains a separate polygon.
