from app import db
from datetime import datetime, timezone


class OsintAsset(db.Model):
    __tablename__ = "osint_assets"

    id                = db.Column(db.String(256), primary_key=True)
    source            = db.Column(db.String(64),  nullable=False, default="manual")
    source_id         = db.Column(db.String(256), nullable=True)
    type              = db.Column(db.String(64),  nullable=False)
    name              = db.Column(db.Text,         nullable=True)
    state             = db.Column(db.String(2),   nullable=True)
    county            = db.Column(db.Text,         nullable=True)
    lat               = db.Column(db.Float,        nullable=True)
    lng               = db.Column(db.Float,        nullable=True)
    geometry_wkt      = db.Column(db.Text,         nullable=True)
    capacity_mw       = db.Column(db.Float,        nullable=True)
    fuel_type         = db.Column(db.String(64),   nullable=True)
    operator          = db.Column(db.Text,         nullable=True)
    owner             = db.Column(db.Text,         nullable=True)
    status            = db.Column(db.String(64),   nullable=True)
    voltage_kv        = db.Column(db.Float,        nullable=True)
    metadata_json     = db.Column(db.Text,         nullable=False, default="{}")
    foreign_link_flag = db.Column(db.Boolean,      nullable=False, default=False)
    updated_at        = db.Column(db.DateTime,     nullable=False,
                                  default=lambda: datetime.now(timezone.utc))
    created_at        = db.Column(db.DateTime,     nullable=False,
                                  default=lambda: datetime.now(timezone.utc))

    def to_geojson_feature(self):
        import json as _json
        props = {
            "id":                 self.id,
            "source":             self.source,
            "type":               self.type,
            "name":               self.name,
            "state":              self.state,
            "county":             self.county,
            "capacity_mw":        self.capacity_mw,
            "fuel_type":          self.fuel_type,
            "operator":           self.operator,
            "owner":              self.owner,
            "status":             self.status,
            "voltage_kv":         self.voltage_kv,
            "foreign_link_flag":  self.foreign_link_flag,
            "geometry_wkt":       self.geometry_wkt,
            "metadata":           _json.loads(self.metadata_json or "{}"),
        }
        geometry = None
        if self.lat is not None and self.lng is not None:
            geometry = {"type": "Point", "coordinates": [self.lng, self.lat]}
        return {"type": "Feature", "id": self.id, "geometry": geometry, "properties": props}


class OsintGridSnapshot(db.Model):
    __tablename__ = "osint_grid_snapshots"
    __table_args__ = (
        db.UniqueConstraint("iso", "timestamp", "metric", "fuel",
                            name="uq_osint_grid_snapshot"),
    )

    id            = db.Column(db.Integer,  primary_key=True, autoincrement=True)
    iso           = db.Column(db.String(16), nullable=False)
    timestamp     = db.Column(db.DateTime,   nullable=False)
    metric        = db.Column(db.String(64), nullable=False)
    fuel          = db.Column(db.String(64), nullable=False, default="")
    value         = db.Column(db.Float,      nullable=False)
    unit          = db.Column(db.String(16), nullable=True)
    metadata_json = db.Column(db.Text,       nullable=False, default="{}")
    created_at    = db.Column(db.DateTime,   nullable=False,
                              default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        import json as _json
        return {
            "iso":       self.iso,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "metric":    self.metric,
            "fuel":      self.fuel,
            "value":     self.value,
            "unit":      self.unit,
        }


class OsintIncident(db.Model):
    __tablename__ = "osint_incidents"

    id            = db.Column(db.String(256), primary_key=True)
    source        = db.Column(db.String(64),  nullable=False)
    source_id     = db.Column(db.String(256), nullable=True)
    type          = db.Column(db.String(64),  nullable=True)
    date          = db.Column(db.Date,        nullable=True)
    state         = db.Column(db.String(2),   nullable=True)
    county        = db.Column(db.Text,        nullable=True)
    operator      = db.Column(db.Text,        nullable=True)
    commodity     = db.Column(db.String(64),  nullable=True)
    lat           = db.Column(db.Float,       nullable=True)
    lng           = db.Column(db.Float,       nullable=True)
    fatalities    = db.Column(db.Integer,     nullable=False, default=0)
    injuries      = db.Column(db.Integer,     nullable=False, default=0)
    cost_usd      = db.Column(db.Float,       nullable=True)
    description   = db.Column(db.Text,        nullable=True)
    metadata_json = db.Column(db.Text,        nullable=False, default="{}")
    updated_at    = db.Column(db.DateTime,    nullable=False,
                              default=lambda: datetime.now(timezone.utc))
    created_at    = db.Column(db.DateTime,    nullable=False,
                              default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id":          self.id,
            "source":      self.source,
            "type":        self.type,
            "date":        self.date.isoformat() if self.date else None,
            "state":       self.state,
            "county":      self.county,
            "operator":    self.operator,
            "commodity":   self.commodity,
            "lat":         self.lat,
            "lng":         self.lng,
            "fatalities":  self.fatalities,
            "injuries":    self.injuries,
            "cost_usd":    self.cost_usd,
            "description": self.description,
        }


class OsintGridAlert(db.Model):
    __tablename__ = "osint_grid_alerts"

    id            = db.Column(db.Integer,    primary_key=True, autoincrement=True)
    iso           = db.Column(db.String(16), nullable=False)
    timestamp     = db.Column(db.DateTime,   nullable=False)
    metric        = db.Column(db.String(64), nullable=False)
    severity      = db.Column(db.String(16), nullable=False)
    message       = db.Column(db.Text,       nullable=False)
    value         = db.Column(db.Float,      nullable=True)
    threshold     = db.Column(db.Float,      nullable=True)
    metadata_json = db.Column(db.Text,       nullable=False, default="{}")
    created_at    = db.Column(db.DateTime,   nullable=False,
                              default=lambda: datetime.now(timezone.utc))
