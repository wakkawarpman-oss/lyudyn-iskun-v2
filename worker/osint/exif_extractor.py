from typing import Dict
from PIL import Image, ExifTags

try:
    from GPSPhoto import gpsphoto
except ImportError:
    gpsphoto = None

class EXIFExtractor:
    @staticmethod
    def _convert_to_degrees(value):
        """Converts EXIF DMS (Degrees, Minutes, Seconds) tuple to decimal degrees."""
        try:
            d = float(value[0])
            m = float(value[1])
            s = float(value[2])
            return d + (m / 60.0) + (s / 3600.0)
        except Exception:
            return None

    def extract(self, image_path: str) -> Dict:
        result = {
            "has_gps": False, "latitude": None, "longitude": None,
            "altitude": None, "timestamp": None, "device": None
        }
        
        # 1. Try GPSPhoto library
        try:
            if gpsphoto:
                gps_data = gpsphoto.getGPSData(image_path)
                if gps_data and 'Latitude' in gps_data and 'Longitude' in gps_data:
                    result["has_gps"] = True
                    result["latitude"] = float(gps_data['Latitude'])
                    result["longitude"] = float(gps_data['Longitude'])
                    result["altitude"] = gps_data.get('Altitude')
                    result["timestamp"] = gps_data.get('DateStamp')
                    return result
        except Exception as e:
            result["error_gpsphoto"] = str(e)

        # 2. Native PIL EXIF fallback
        try:
            with Image.open(image_path) as img:
                exif_raw = img._getexif()
                if not exif_raw:
                    return result

                exif = {ExifTags.TAGS.get(k, k): v for k, v in exif_raw.items()}
                
                # Extract device info
                make = exif.get('Make', '')
                model = exif.get('Model', '')
                if make or model:
                    result["device"] = f"{make} {model}".strip()

                # Extract timestamp
                if 'DateTimeOriginal' in exif:
                    result["timestamp"] = str(exif['DateTimeOriginal'])
                elif 'DateTime' in exif:
                    result["timestamp"] = str(exif['DateTime'])

                # Extract GPS
                gps_info = exif.get('GPSInfo')
                if gps_info:
                    gps_tags = {}
                    for key in gps_info.keys():
                        sub_tag = ExifTags.GPSTAGS.get(key, key)
                        gps_tags[sub_tag] = gps_info[key]

                    lat_raw = gps_tags.get('GPSLatitude')
                    lat_ref = gps_tags.get('GPSLatitudeRef', 'N')
                    lon_raw = gps_tags.get('GPSLongitude')
                    lon_ref = gps_tags.get('GPSLongitudeRef', 'E')

                    if lat_raw and lon_raw:
                        lat = self._convert_to_degrees(lat_raw)
                        lon = self._convert_to_degrees(lon_raw)

                        if lat is not None and lon is not None:
                            if lat_ref != 'N':
                                lat = -lat
                            if lon_ref != 'E':
                                lon = -lon

                            result["has_gps"] = True
                            result["latitude"] = round(lat, 6)
                            result["longitude"] = round(lon, 6)
                            
                        if 'GPSAltitude' in gps_tags:
                            try:
                                result["altitude"] = float(gps_tags['GPSAltitude'])
                            except Exception:
                                pass
        except Exception as e:
            result["error_pil"] = str(e)

        return result
