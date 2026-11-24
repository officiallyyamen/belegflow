class Konflikt(Exception):
    def __init__(self, text: str, **angaben):
        super().__init__(text)
        self.angaben = angaben


class Ungueltig(Exception):
    pass


class Verboten(Exception):
    pass


class NichtGefunden(Exception):
    pass
