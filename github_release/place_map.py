"""조회된 좌표로만 추천 장소 지도를 구성합니다."""
from hashlib import sha256
from html import escape
import json
import math
from urllib.parse import urlparse

import folium
from folium.plugins import MarkerCluster


def plan_map_places(plan):
    candidates = {p["map_url"]: p for p in plan.get("candidates", []) if p.get("map_url")}
    return [{**candidates.get(v.get("map_url"), {}), **v} for v in plan.get("visits", [])]


def build_place_map(places):
    valid, missing = [], 0
    for order, place in enumerate(places, 1):
        try:
            lat, lon = float(place["y"]), float(place["x"])
            if not math.isfinite(lat) or not math.isfinite(lon) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError
        except (KeyError, TypeError, ValueError):
            missing += 1
            continue
        valid.append((order, place, lat, lon))
    if not valid:
        return None, {"marker_count": 0, "missing_count": missing}
    bounds = [[min(p[2] for p in valid), min(p[3] for p in valid)],
              [max(p[2] for p in valid), max(p[3] for p in valid)]]
    center = [(bounds[0][0]+bounds[1][0])/2, (bounds[0][1]+bounds[1][1])/2]
    result = folium.Map(location=center, zoom_start=15, tiles="OpenStreetMap", control_scale=True, scrollWheelZoom=False)
    group = folium.FeatureGroup(name="추천 장소")
    cluster = MarkerCluster(options={"maxClusterRadius": 25, "spiderfyOnMaxZoom": True}).add_to(group)
    for order, place, lat, lon in valid:
        name, address = escape(str(place.get("name", "장소"))), escape(str(place.get("address") or "주소 정보 없음"))
        time = escape(f'{place.get("day", "")}일차 · {place.get("time", "")}') if place.get("day") else ""
        url = place.get("map_url", "")
        parsed = urlparse(url)
        link = f'<br><a href="{escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">카카오맵 상세 보기</a>' if parsed.scheme == "https" and parsed.hostname == "place.map.kakao.com" else ""
        popup = f'<strong>{order}. {name}</strong><br>{time}<br>{address}{link}'
        icon = folium.DivIcon(html=f'<div style="background:#286a58;color:white;border:2px solid #e1f2e5;border-radius:50%;width:30px;height:30px;line-height:26px;text-align:center;font-weight:bold;box-shadow:0 2px 6px #0005">{order}</div>', icon_size=(30, 30), icon_anchor=(15, 15))
        folium.Marker(location=[lat, lon], tooltip=f"{order}. {name}", popup=folium.Popup(popup, max_width=300), icon=icon).add_to(cluster)
    group.add_to(result)
    if bounds[0] != bounds[1]:
        result.fit_bounds(bounds, padding=(35, 35), max_zoom=15)
    fingerprint = sha256(json.dumps([(p[0], p[1].get("name"), p[1].get("time"), p[2], p[3]) for p in valid], ensure_ascii=False).encode()).hexdigest()[:16]
    return result, {"marker_count": len(valid), "missing_count": missing, "center": center, "bounds": bounds, "fingerprint": fingerprint}


def show_place_map(places, key):
    import streamlit as st
    from streamlit_folium import st_folium
    map_object, info = build_place_map(places)
    if map_object is None:
        st.info("조회 결과에 유효한 좌표가 없어 지도를 표시할 수 없습니다. 장소의 지도 링크를 확인해 주세요.")
        return
    st.caption(f'추천 장소 {info["marker_count"]}곳 · 전체 장소가 보이도록 지도 시점을 맞췄습니다. 마커를 누르면 주소와 상세 링크를 확인할 수 있습니다.')
    st_folium(map_object, key=f'{key}_{info["fingerprint"]}', height=400, use_container_width=True, returned_objects=[])
    if info["missing_count"]:
        st.caption(f'좌표를 확인할 수 없는 {info["missing_count"]}곳은 지도에서 제외했습니다.')
