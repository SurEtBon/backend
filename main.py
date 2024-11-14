import datetime
import os
from typing import List, Optional
from pydantic import BaseModel
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from google.cloud import bigquery
import json

class ControleSanitaire(BaseModel):
    iea_date_inspection: datetime.date
    iea_app_code_synthese_eval_sanit: int

class Restaurant(BaseModel):
    iofff_name: str
    iofff_meta_geo_point_latitude: float
    iofff_meta_geo_point_longitude: float
    iea_app_libelle_etablissement: str
    iea_date_inspection: datetime.date
    iea_synthese_eval_sanit: str
    iea_app_code_synthese_eval_sanit: int
    iea_full_address: str
    nb_inspections: int
    inspections: List[ControleSanitaire]
    sgmppd_rating: Optional[float]
    sgmppd_googleMapsUri: Optional[str]
    sgmppd_userRatingCount: Optional[int]
    stld_web_url: Optional[str]
    stld_rating: Optional[float]
    stld_num_reviews: Optional[int]

class Restaurants(BaseModel):
    restaurants: List[Restaurant]

class BoundingBox(BaseModel):
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
def get_restaurants(bounding_box: BoundingBox) -> Restaurants:
    client = bigquery.Client.from_service_account_json(os.getenv("GCP_SERVICE_ACCOUNT_KEY_JSON_FILEPATH"))

    QUERY = (
        'SELECT '
        '* '
        'FROM `' + os.getenv("GCP_PROJECT_ID") + '.' + os.getenv("BQ_DATASET_ID") + '.' + os.getenv("BQ_TABLE_ID") + '` '
        'WHERE '
        'iofff_meta_geo_point_latitude BETWEEN ' + str(bounding_box.latitude_minimum) + ' AND ' + str(bounding_box.latitude_maximum) + ' '
        'AND '
        'iofff_meta_geo_point_longitude BETWEEN ' + str(bounding_box.longitude_minimum) + ' AND ' + str(bounding_box.longitude_maximum)
    )
    query_job = client.query(QUERY)
    rows = query_job.result()
    restaurants = []
    for row in rows:
        inspections = []
        for inspection_str in row["inspections"]:
            inspection_dict = json.loads(inspection_str)
            inspections.append(inspection_dict)
        restaurants.append({
            'iofff_name': row["iofff_name"],
            'iofff_meta_geo_point_latitude': row["iofff_meta_geo_point_latitude"],
            'iofff_meta_geo_point_longitude': row["iofff_meta_geo_point_longitude"],
            'iea_app_libelle_etablissement': row["iea_app_libelle_etablissement"],
            'iea_date_inspection': row["iea_date_inspection"],
            'iea_synthese_eval_sanit': row["iea_synthese_eval_sanit"],
            'iea_app_code_synthese_eval_sanit': row["iea_app_code_synthese_eval_sanit"],
            'iea_full_address': row["iea_full_address"],
            'nb_inspections': row["nb_inspections"],
            'inspections': inspections,
            'sgmppd_rating': row["sgmppd_rating"],
            'sgmppd_googleMapsUri': row["sgmppd_googleMapsUri"],
            'sgmppd_userRatingCount': row["sgmppd_userRatingCount"],
            'stld_web_url': row["stld_web_url"],
            'stld_rating': row["stld_rating"],
            'stld_num_reviews': row["stld_num_reviews"]
        })
    return Restaurants(restaurants = restaurants)