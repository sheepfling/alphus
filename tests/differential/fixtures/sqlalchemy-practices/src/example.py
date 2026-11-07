from sqlalchemy.orm import Session


class User:
    pass


def load(session: Session) -> list[User]:
    return session.query(User).all()
