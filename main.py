import datetime
import os
from typing import List, Optional
from pydantic import BaseModel
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from google.cloud import bigquery
import json

class ControleSanitaire(BaseModel):
    ea_date_inspection: datetime.date
    ea_app_code_synthese_eval_sanit: int

class Restaurant(BaseModel):
    osm_ffs_name: str
    osm_ffs_meta_geo_point_latitude: float
    osm_ffs_meta_geo_point_longitude: float
    ea_app_libelle_etablissement: str
    ea_date_inspection: datetime.date
    ea_synthese_eval_sanit: str
    ea_app_code_synthese_eval_sanit: int
    ea_full_address: str
    nombre_controles_sanitaires: int
    controles_sanitaires: List[ControleSanitaire]
    gmp_pd_rating: Optional[float]
    gmp_pd_googleMapsUri: Optional[str]
    gmp_pd_userRatingCount: Optional[int]
    t_ld_web_url: Optional[str]
    t_ld_rating: Optional[float]
    t_ld_num_reviews: Optional[int]

class Restaurants(BaseModel):
    restaurants: List[Restaurant]

class BoiteEnglobante(BaseModel):
    latitude_minimum: float
    longitude_minimum: float
    latitude_maximum: float
    longitude_maximum: float

app = FastAPI()

origins = [
    os.getenv("FRONTEND_URL")
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/get_restaurants", response_model = Restaurants)
def get_restaurants(boite_englobante: BoiteEnglobante) -> Restaurants:
    client = bigquery.Client.from_service_account_json(os.getenv("GCP_SERVICE_ACCOUNT_KEY_JSON_FILEPATH"))

    QUERY = (
        'SELECT '
        '* '
        'FROM `' + os.getenv("GCP_PROJECT_ID") + '.' + os.getenv("BQ_DATASET_ID") + '.' + os.getenv("BQ_TABLE_ID") + '` '
        'WHERE '
        '`osm_ffs-meta_geo_point_latitude` BETWEEN ' + str(boite_englobante.latitude_minimum) + ' AND ' + str(boite_englobante.latitude_maximum) + ' '
        'AND '
        '`osm_ffs-meta_geo_point_longitude` BETWEEN ' + str(boite_englobante.longitude_minimum) + ' AND ' + str(boite_englobante.longitude_maximum)
    )
    query_job = client.query(QUERY)
    rows = query_job.result()
    restaurants = []
    for row in rows:
        controles_sanitaires = []
        for controle_sanitaire in row["controles_sanitaires"]:
            controles_sanitaires.append({
                'ea_date_inspection': controle_sanitaire["ea-date_inspection"],
                'ea_app_code_synthese_eval_sanit': controle_sanitaire["ea-app_code_synthese_eval_sanit"]
            })
        restaurants.append({
            'osm_ffs_name': row["osm_ffs-name"],
            'osm_ffs_meta_geo_point_latitude': row["osm_ffs-meta_geo_point_latitude"],
            'osm_ffs_meta_geo_point_longitude': row["osm_ffs-meta_geo_point_longitude"],
            'ea_app_libelle_etablissement': row["ea-app_libelle_etablissement"],
            'ea_date_inspection': row["ea-date_inspection"],
            'ea_synthese_eval_sanit': row["ea-synthese_eval_sanit"],
            'ea_app_code_synthese_eval_sanit': row["ea-app_code_synthese_eval_sanit"],
            'ea_full_address': row["ea-full_address"],
            'nombre_controles_sanitaires': row["nombre_controles_sanitaires"],
            'controles_sanitaires': controles_sanitaires,
            'gmp_pd_rating': row["gmp_pd-rating"],
            'gmp_pd_googleMapsUri': row["gmp_pd-googleMapsUri"],
            'gmp_pd_userRatingCount': row["gmp_pd-userRatingCount"],
            't_ld_web_url': row["t_ld-web_url"],
            't_ld_rating': row["t_ld-rating"],
            't_ld_num_reviews': row["t_ld-num_reviews"]
        })
    return Restaurants(restaurants = restaurants)