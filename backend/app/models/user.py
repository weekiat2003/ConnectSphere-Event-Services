from app.common.time import utcnow


from app.extensions import db

created_at = db.Column(db.DateTime, default=utcnow)
updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)


class Organisation(db.Model):
    __tablename__ = "organisations"

    id = db.Column(db.BigInteger, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow())


class Role(db.Model):
    __tablename__ = "roles"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)


user_roles = db.Table(
    "user_roles",
    db.Column("user_id", db.BigInteger, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    db.Column("role_id", db.SmallInteger, db.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.BigInteger, primary_key=True)
    organisation_id = db.Column(db.BigInteger, db.ForeignKey("organisations.id"), nullable=True)
    name = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=utcnow())
    updated_at = db.Column(db.DateTime, default=utcnow(), onupdate=utcnow())

    roles = db.relationship("Role", secondary=user_roles, backref="users")

    def has_role(self, role_name):
        return any(r.name == role_name for r in self.roles)

    def role_names(self):
        return [r.name for r in self.roles]

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "organisationId": self.organisation_id,
            "roles": self.role_names(),
        }


class RefreshToken(db.Model):
    __tablename__ = "refresh_tokens"

    id = db.Column(db.BigInteger, primary_key=True)
    user_id = db.Column(db.BigInteger, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    jti = db.Column(db.String(36), unique=True, nullable=False)
    revoked = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=utcnow())
    expires_at = db.Column(db.DateTime, nullable=False)
