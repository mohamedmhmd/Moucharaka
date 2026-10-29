"""Administrative divisions of Mauritania (wilayas and main moughataas).

Loaded by a data migration; admins can complete or correct the list from the
admin site. Coordinates are approximate town centres used to centre maps.
"""

WILAYAS = [
    # code, fr, ar, [(fr, ar, lat, lng), ...]
    ("NKN", "Nouakchott-Nord", "نواكشوط الشمالية", [
        ("Dar Naïm", "دار النعيم", 18.122, -15.940),
        ("Teyarett", "تيارت", 18.122, -15.965),
        ("Toujounine", "توجنين", 18.069, -15.906),
    ]),
    ("NKO", "Nouakchott-Ouest", "نواكشوط الغربية", [
        ("Tevragh Zeina", "تفرغ زينة", 18.100, -15.990),
        ("Ksar", "لكصر", 18.103, -15.960),
        ("Sebkha", "السبخة", 18.073, -15.985),
    ]),
    ("NKS", "Nouakchott-Sud", "نواكشوط الجنوبية", [
        ("Arafat", "عرفات", 18.050, -15.950),
        ("El Mina", "الميناء", 18.045, -15.990),
        ("Riyad", "الرياض", 18.010, -15.940),
    ]),
    ("DNO", "Dakhlet Nouadhibou", "داخلت نواذيبو", [
        ("Nouadhibou", "نواذيبو", 20.942, -17.038),
        ("Chami", "الشامي", 20.040, -15.950),
    ]),
    ("TRZ", "Trarza", "الترارزة", [
        ("Rosso", "روصو", 16.513, -15.805),
        ("Boutilimit", "بوتلميت", 17.550, -14.700),
        ("Mederdra", "المذرذرة", 16.920, -15.660),
        ("Keur Macène", "كرمسين", 16.550, -16.240),
        ("R'Kiz", "اركيز", 16.880, -15.230),
        ("Ouad Naga", "واد الناقة", 17.970, -15.510),
    ]),
    ("ADR", "Adrar", "آدرار", [
        ("Atar", "أطار", 20.517, -13.050),
        ("Chinguetti", "شنقيط", 20.462, -12.364),
        ("Ouadane", "وادان", 20.928, -11.623),
        ("Aoujeft", "أوجفت", 20.030, -13.050),
    ]),
    ("BRK", "Brakna", "البراكنة", [
        ("Aleg", "ألاك", 17.053, -13.916),
        ("Boghé", "بوكي", 16.590, -14.270),
        ("Bababé", "بابابي", 16.330, -13.950),
        ("M'Bagne", "امبان", 16.150, -13.780),
        ("Magta Lahjar", "مقطع لحجار", 17.500, -13.080),
    ]),
    ("GRG", "Gorgol", "كوركول", [
        ("Kaédi", "كيهيدي", 16.150, -13.505),
        ("M'Bout", "امبود", 16.020, -12.580),
        ("Monguel", "مونكل", 16.420, -13.070),
        ("Maghama", "مقامة", 15.510, -12.850),
    ]),
    ("ASB", "Assaba", "لعصابة", [
        ("Kiffa", "كيفة", 16.620, -11.404),
        ("Guerou", "كرو", 16.810, -11.830),
        ("Kankossa", "كنكوصة", 15.930, -11.520),
        ("Barkéwol", "باركيول", 16.640, -12.500),
        ("Boumdeid", "بومديد", 17.430, -11.340),
    ]),
    ("HEC", "Hodh Ech Chargui", "الحوض الشرقي", [
        ("Néma", "النعمة", 16.617, -7.258),
        ("Amourj", "امرج", 16.070, -7.200),
        ("Bassiknou", "باسكنو", 15.870, -5.960),
        ("Djiguenni", "جكني", 15.730, -8.680),
        ("Oualata", "ولاتة", 17.300, -7.020),
        ("Timbédra", "تمبدغة", 16.240, -8.160),
    ]),
    ("HEG", "Hodh El Gharbi", "الحوض الغربي", [
        ("Aïoun", "العيون", 16.660, -9.620),
        ("Kobenni", "كوبني", 15.870, -9.400),
        ("Tamchekett", "تامشكط", 17.240, -10.670),
        ("Tintane", "الطينطان", 16.410, -10.170),
    ]),
    ("TAG", "Tagant", "تكانت", [
        ("Tidjikja", "تجكجة", 18.556, -11.427),
        ("Moudjéria", "المجرية", 17.880, -12.330),
        ("Tichitt", "تيشيت", 18.450, -9.510),
    ]),
    ("GDM", "Guidimakha", "كيدي ماغة", [
        ("Sélibaby", "سيلبابي", 15.159, -12.184),
        ("Ould Yengé", "ولد ينج", 15.540, -11.720),
    ]),
    ("TZM", "Tiris Zemmour", "تيرس زمور", [
        ("Zouérate", "ازويرات", 22.735, -12.471),
        ("F'Dérik", "افديرك", 22.680, -12.710),
        ("Bir Moghreïn", "بير أم اكرين", 25.230, -11.590),
    ]),
    ("INC", "Inchiri", "إينشيري", [
        ("Akjoujt", "أكجوجت", 19.747, -14.385),
    ]),
]


def load_reference(Wilaya, Moughataa):
    for order, (code, fr, ar, moughataas) in enumerate(WILAYAS):
        w, _ = Wilaya.objects.update_or_create(code=code, defaults={"name_fr": fr, "name_ar": ar, "order": order})
        for mfr, mar, lat, lng in moughataas:
            Moughataa.objects.update_or_create(
                wilaya=w, name_fr=mfr, defaults={"name_ar": mar, "latitude": lat, "longitude": lng})
