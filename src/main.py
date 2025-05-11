from flask import Flask
import math
import requests
import json
import os
from shapely.geometry import Point, Polygon, MultiPolygon

app = Flask(__name__)
WMS_URL = f"https://uom.caac.gov.cn/map/airspace/wms?token={os.getenv('WMS_TOKEN')}"

# 修正后的省份分组映射
PROVINCE_GROUPS = {
    'north': ['12', '13', '14', '15'],                   # 华北地区
    'northeast': ['21', '22', '23'],                     # 东北地区
    'east': ['31', '32', '33', '34', '35', '36', '37'],  # 华东地区
    'central': ['41', '42', '43', '44', '45', '46'],     # 华中地区
    'southwest': ['50', '51', '52', '53', '54'],         # 西南地区
    'northwest': ['62', '63', '64', '65']                # 西北地区 (甘肃62, 宁夏64, 青海63, 新疆65)
}

# 反转映射：从省份代码到所属组
CODE_TO_GROUP = {code: group for group, codes in PROVINCE_GROUPS.items() for code in codes}

# 缓存省份几何信息
province_geometries = {}

def load_province_geometries():
    global province_geometries
    try:
        with open('./res/china_new.geojson', 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        for feature in data.get('features', []):
            properties = feature.get('properties', {})
            code = str(properties.get('省级码', ''))[:2]  # 使用省级码作为省份代码
            
            if not code:
                print(f"Skipping feature without valid code: {properties}")
                continue
                
            geometry = feature.get('geometry', {})
            geometry_type = geometry.get('type')
            coordinates = geometry.get('coordinates', [])
            
            try:
                if geometry_type == 'Polygon':
                    exterior = coordinates[0]
                    interiors = coordinates[1:]
                    province_geometries[code] = Polygon(exterior, interiors)
                elif geometry_type == 'MultiPolygon':
                    polygons = []
                    for polygon_coords in coordinates:
                        exterior = polygon_coords[0]
                        interiors = polygon_coords[1:]
                        polygons.append(Polygon(exterior, interiors))
                    province_geometries[code] = MultiPolygon(polygons)
                
                print(f"Loaded geometry for code {code}")
            except Exception as e:
                print(f"Error processing geometry for code {code}: {e}")
        
        print(f"Loaded {len(province_geometries)} province geometries")
    except Exception as e:
        print(f"Error loading province geometries: {e}")
        province_geometries = {}


# def calculate_bbox(z, x, y, tile_size=256):
#     """
#     计算OSM XYZ系统中瓦片在EPSG:3857 (Web Mercator) 下的边界框
    
#     参数:
#     z (int): 缩放级别
#     x (int): OSM XYZ系统中的X坐标
#     y (int): OSM XYZ系统中的Y坐标
#     tile_size (int): 瓦片像素大小，默认为256
    
#     返回:
#     tuple: 边界框坐标 (minx, miny, maxx, maxy)，单位为米
#     """
#     import math
    
#     # OSM XYZ到TMS坐标的转换
#     tms_y = (2 ** z - 1) - y
    
#     # 常量定义
#     earth_radius = 6378137  # WGS84椭球体半径（米）
#     origin_shift = 2 * math.pi * earth_radius / 2.0  # 半周长
    
#     # 计算分辨率（米/像素）
#     res = (2 * origin_shift) / (tile_size * 2 ** z)
    
#     # 计算边界框坐标
#     minx = x * tile_size * res - origin_shift
#     maxx = (x + 1) * tile_size * res - origin_shift
#     miny = origin_shift - (tms_y + 1) * tile_size * res
#     maxy = origin_shift - tms_y * tile_size * res
    
#     return minx, miny, maxx, maxy

def calculate_bbox(z, x, y, tile_size=256):
    """
    计算Google Maps XYZ瓦片系统中瓦片在EPSG:3857 (Web Mercator) 下的边界框
    
    参数:
    z (int): 缩放级别
    x (int): XYZ系统中的X坐标
    y (int): XYZ系统中的Y坐标
    tile_size (int): 瓦片像素大小，默认为256
    
    返回:
    tuple: 边界框坐标 (minx, miny, maxx, maxy)，单位为米
    """
    import math
    
    # 常量定义
    earth_radius = 6378137  # WGS84椭球体半径（米）
    origin_shift = 2 * math.pi * earth_radius / 2.0  # 半周长
    
    # 计算分辨率（米/像素）
    res = (2 * origin_shift) / (tile_size * 2 ** z)
    
    # 直接计算边界框（XYZ系统无需转换）
    minx = x * tile_size * res - origin_shift
    maxx = (x + 1) * tile_size * res - origin_shift
    miny = origin_shift - (y + 1) * tile_size * res
    maxy = origin_shift - y * tile_size * res
    
    return minx, miny, maxx, maxy


def mercator_to_lnglat(x, y):
    """将EPSG:3857坐标转换为经纬度"""
    earth_radius = 6378137
    lng = (x / earth_radius) * 180.0 / math.pi
    lat = (math.atan(math.exp(y / earth_radius)) * 2 - math.pi/2) * 180.0 / math.pi
    return lng, lat

def get_province_group(z, x, y):
    """Determine which predefined province group contains this tile"""
    if z < 6:  # Show all regions at low zoom levels
        return sum(PROVINCE_GROUPS.values(), [])
        
    # 计算瓦片的中心点和四个角点
    minx, miny, maxx, maxy = calculate_bbox(z, x, y)
    # print(f"Bounding box coordinates:")
    # print(f"minx (west): {minx}")
    # print(f"miny (south): {miny}")
    # print(f"maxx (east): {maxx}")
    # print(f"maxy (north): {maxy}")
    
    center_x, center_y = (minx + maxx) / 2, (miny + maxy) / 2
    points = [
        mercator_to_lnglat(center_x, center_y),  # 中心点
        mercator_to_lnglat(minx, miny),          # 左下角
        mercator_to_lnglat(maxx, miny),          # 右下角
        mercator_to_lnglat(minx, maxy),          # 左上角
        mercator_to_lnglat(maxx, maxy),          # 右上角
        # 添加更多采样点以提高准确性
        mercator_to_lnglat((minx+maxx)/2, miny),  # 下边缘中点
        mercator_to_lnglat((minx+maxx)/2, maxy),  # 上边缘中点
        mercator_to_lnglat(minx, (miny+maxy)/2),  # 左边缘中点
        mercator_to_lnglat(maxx, (miny+maxy)/2),  # 右边缘中点
    ]
    
    # 检查每个点位于哪个省份
    matched_provinces = set()
    for lng, lat in points:
        point = Point(lng, lat)
        for code, geometry in province_geometries.items():
            if geometry.contains(point):
                matched_provinces.add(code)
                break  # 找到匹配省份后不再继续检查
    
    # 如果没有匹配到任何省份，尝试使用更精确的匹配方法
    if not matched_provinces:
        print(f"No province matched for tile ({z}, {x}, {y}), trying alternative method")
        # 计算瓦片的所有边界点
        edge_points = []
        step = 10  # 采样步长
        for i in range(0, 256, step):
            for j in [0, 255]:
                mx = minx + (maxx - minx) * i / 256
                my = miny + (maxy - miny) * j / 256
                edge_points.append(mercator_to_lnglat(mx, my))
            for j in range(0, 256, step):
                mx = minx if i == 0 else maxx
                my = miny + (maxy - miny) * j / 256
                edge_points.append(mercator_to_lnglat(mx, my))
        
        # 再次尝试匹配
        for lng, lat in edge_points:
            point = Point(lng, lat)
            for code, geometry in province_geometries.items():
                if geometry.contains(point):
                    matched_provinces.add(code)
                    break  # 找到匹配省份后不再继续检查
            
            if matched_provinces:  # 如果找到匹配，不再继续检查
                break
    
    # 如果仍然没有匹配到任何省份，使用基于经纬度的旧逻辑作为后备
    if not matched_provinces:
        print(f"Still no province matched for tile ({z}, {x}, {y}), using fallback logic")
        lng, lat = points[0]  # 使用中心点的经纬度
        # 优化后的经纬度分区逻辑
        if lat > 40 and lng < 125: return PROVINCE_GROUPS['northeast']
        elif lng < 105:
            if lat > 38: return PROVINCE_GROUPS['northwest']
            else: return PROVINCE_GROUPS['southwest']
        elif lng < 115: return PROVINCE_GROUPS['central']
        elif lng < 122: return PROVINCE_GROUPS['east']
        else: return PROVINCE_GROUPS['north']
    
    # 获取匹配省份的组
    groups = {CODE_TO_GROUP.get(code, 'unknown') for code in matched_provinces}
    # 展平所有匹配组的省份代码
    result = sum([PROVINCE_GROUPS.get(group, []) for group in groups], [])
    
    # print(f"Tile ({z}, {x}, {y}) matched provinces: {matched_provinces}, groups: {groups}, result: {result}")
    return result

def wms_to_xyz(z, x, y, wms_url):
    """Convert XYZ tile request to WMS request with proper province groups"""
    provinces = get_province_group(z, x, y)
    layers = ",".join([f"QGSFKYFW:sf{code}0000" for code in provinces])
    styles = ",".join(["QGSFKYFW:shifeikongyu"] * len(provinces))
    
    params = {
        "service": "WMS",
        "version": "1.1.0",
        "request": "GetMap",
        "layers": layers,
        "styles": styles,
        "bbox": calculate_bbox(z, x, y),
        "width": 256,
        "height": 256,
        "srs": "EPSG:3857",
        "format": "image/png8",
        "transparent": "true"
    }
    # print("wms_to_xyz wms_url：{} params：{}".format(wms_url, params))
    response = requests.get(wms_url, params=params, timeout=10)

    # request = response.request
    # # 获取请求 URL
    # request_url = response.request.url
    # print("request_url:{}".format(request_url))

    return response.content

@app.route('/<int:z>/<int:x>/<int:y>.png')
def get_tile(z, x, y):
    """Tile endpoint serving WMS-proxied content"""
    try:
        tile_data = wms_to_xyz(z, x, y, WMS_URL)
        return tile_data, 200, {'Content-Type': 'image/png'}
    except Exception as e:
        print(f"Error generating tile: {e}")
        # Return transparent 1x1 PNG on error
        return (b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82', 
                200, 
                {'Content-Type': 'image/png'})


if __name__ == '__main__':
    load_province_geometries()  # 启动时加载省份几何信息
    print("Province group mappings:", PROVINCE_GROUPS)
    # 验证特定瓦片
    test_z, test_x, test_y = 18, 215204, 163762
    test_provinces = get_province_group(test_z, test_x, test_y)
    print(f"Test tile ({test_z}, {test_x}, {test_y}) provinces: {test_provinces}")
   
    test_z, test_x, test_y = 18, 215207, 98384 
    test_provinces = get_province_group(test_z, test_x, test_y)
    print(f"Test tile ({test_z}, {test_x}, {test_y}) provinces: {test_provinces}")

    app.run(host='0.0.0.0', port=5000)