"""Default question bank, loaded by a data migration. Admins can add, edit,
reorder or deactivate questions in the admin (Projets › Sections du
questionnaire) without touching code.

Format: (code, type, fr, ar, applies_to, required, public, choices, help_fr, help_ar)
choices: list of (value, fr, ar)
"""
ALL = "boutique,deal,company"
B, D, C = "boutique", "deal", "company"

YES_NO_LEVEL = [("low", "Faible", "ضعيف"), ("medium", "Moyen", "متوسط"), ("high", "Élevé", "مرتفع")]

SECTIONS = [
    ("Le porteur du projet", "صاحب المشروع", [
        ("owner_experience_years", "number", "Depuis combien d'années exercez-vous dans ce domaine ?",
         "منذ كم سنة تعمل في هذا المجال؟", ALL, True, True, [], "", ""),
        ("owner_education", "choice", "Votre niveau d'études", "مستواك الدراسي", ALL, False, True, [
            ("none", "Pas de scolarité", "بدون تعليم"), ("mahadra", "Mahadra", "المحظرة"),
            ("primary", "Primaire", "ابتدائي"), ("secondary", "Collège / lycée", "إعدادي / ثانوي"),
            ("vocational", "Formation professionnelle", "تكوين مهني"), ("university", "Université", "جامعي")], "", ""),
        ("owner_previous_business", "textarea", "Avez-vous déjà créé ou géré un commerce ? Racontez brièvement.",
         "هل سبق لك أن أنشأت أو أدرت تجارة؟ احكِ لنا باختصار.", ALL, True, True, [], "", ""),
        ("owner_other_income", "bool", "Avez-vous d'autres sources de revenus ?", "هل لديك مصادر دخل أخرى؟",
         ALL, False, True, [], "", ""),
        ("owner_previous_financing", "multi", "Avez-vous déjà été financé ? Par qui ?",
         "هل سبق أن حصلت على تمويل؟ من أي جهة؟", ALL, False, True, [
             ("never", "Jamais", "أبداً"), ("family", "Famille / amis", "العائلة / الأصدقاء"),
             ("tontine", "Tontine / caisse d'entraide", "صندوق تضامني (تونتين)"),
             ("microfinance", "Microfinance", "مؤسسة تمويل أصغر"), ("bank", "Banque classique", "بنك تقليدي"),
             ("islamic_bank", "Banque islamique", "بنك إسلامي"), ("supplier", "Crédit fournisseur", "دين من المورّد")],
         "", ""),
        ("owner_repaid", "choice", "Ces financements ont-ils été remboursés ?", "هل تم سداد هذه التمويلات؟",
         ALL, False, True, [
             ("on_time", "Oui, à temps", "نعم، في الآجال"), ("late", "Oui, avec du retard", "نعم، مع تأخير"),
             ("ongoing", "En cours de remboursement", "قيد السداد"), ("na", "Pas concerné", "لا ينطبق")], "", ""),
        ("owner_time_commitment", "choice", "Temps que vous consacrez au projet", "الوقت الذي تخصصه للمشروع",
         ALL, True, True, [("full", "Plein temps", "دوام كامل"), ("part", "Temps partiel", "دوام جزئي")], "", ""),
        ("owner_dependents", "number", "Nombre de personnes à votre charge", "عدد الأشخاص الذين تعيلهم",
         ALL, False, False, [], "Information confidentielle, non publiée.", "معلومة سرية، لا تُنشر."),
        ("owner_references", "textarea",
         "Personnes pouvant témoigner de votre sérieux (imam, chef de quartier, fournisseur, ancien associé)",
         "أشخاص يمكنهم الشهادة على جديتك (إمام، شيخ الحي، مورّد، شريك سابق)", ALL, False, False, [],
         "Nom et téléphone. Confidentiel : utilisé par l'équipe pour vérifier.",
         "الاسم والهاتف. سري: يستخدمه الفريق للتحقق."),
    ]),
    ("Activité et marché", "النشاط والسوق", [
        ("main_customers", "textarea", "Qui sont vos clients ?", "من هم زبائنك؟", ALL, True, True, [],
         "Familles du quartier, fonctionnaires, écoles, restaurants, autres commerçants…",
         "أسر الحي، موظفون، مدارس، مطاعم، تجار آخرون…"),
        ("customer_loyalty", "choice", "Vos clients sont surtout…", "زبائنك في الغالب…", f"{B},{C}", False, True, [
            ("regular", "Des habitués", "زبائن دائمون"), ("mixed", "Un mélange", "مزيج"),
            ("passing", "Des clients de passage", "زبائن عابرون")], "", ""),
        ("competition_level", "choice", "Niveau de concurrence autour de vous", "مستوى المنافسة من حولك",
         ALL, True, True, YES_NO_LEVEL, "", ""),
        ("differentiation", "textarea", "Pourquoi les clients viendront chez vous plutôt qu'ailleurs ?",
         "لماذا يأتي الزبائن إليك بدل غيرك؟", ALL, True, True, [], "", ""),
        ("price_strategy", "choice", "Vos prix par rapport aux concurrents", "أسعارك مقارنة بالمنافسين",
         ALL, False, True, [("lower", "Moins chers", "أرخص"), ("same", "Identiques", "مماثلة"),
                            ("higher", "Plus chers (qualité, service)", "أغلى (جودة، خدمة)")], "", ""),
        ("demand_trend", "choice", "La demande dans votre marché est…", "الطلب في سوقك…", ALL, True, True, [
            ("growing", "En hausse", "في ارتفاع"), ("stable", "Stable", "مستقر"),
            ("declining", "En baisse", "في انخفاض")], "", ""),
        ("delivery", "bool", "Proposez-vous la livraison à domicile ?", "هل توفر خدمة التوصيل للمنازل؟",
         f"{B},{C}", False, True, [], "", ""),
        ("digital_sales", "multi", "Utilisez-vous ces outils pour vendre ?", "هل تستعمل هذه الوسائل للبيع؟",
         ALL, False, True, [("whatsapp", "WhatsApp", "واتساب"), ("facebook", "Facebook", "فيسبوك"),
                            ("tiktok", "TikTok", "تيك توك"), ("none", "Aucun", "لا شيء")], "", ""),
    ]),
    ("Gestion et organisation", "التسيير والتنظيم", [
        ("bookkeeping", "choice", "Comment suivez-vous vos ventes et dépenses ?", "كيف تتابع مبيعاتك ومصاريفك؟",
         ALL, True, True, [("none", "Je ne note rien", "لا أدوّن شيئاً"), ("notebook", "Un cahier", "دفتر"),
                           ("excel", "Un tableur", "جدول إلكتروني"), ("software", "Un logiciel de caisse", "برنامج محاسبة")],
         "", ""),
        ("separate_cash", "bool", "Séparez-vous l'argent du commerce de celui de la famille ?",
         "هل تفصل مال التجارة عن مال الأسرة؟", ALL, True, True, [], "", ""),
        ("stock_control", "choice", "Faites-vous l'inventaire du stock ?", "هل تجرد المخزون؟", f"{B},{D}", False, True, [
            ("never", "Jamais", "أبداً"), ("monthly", "Chaque mois", "كل شهر"), ("weekly", "Chaque semaine", "كل أسبوع"),
            ("daily", "Chaque jour", "كل يوم")], "", ""),
        ("absent_manager", "text", "Qui gère l'activité en votre absence ?", "من يدير النشاط في غيابك؟",
         ALL, False, True, [], "", ""),
        ("staff_family", "bool", "Vos employés sont-ils des membres de votre famille ?", "هل عمالك من أفراد عائلتك؟",
         f"{B},{C}", False, True, [], "", ""),
        ("reporting_commitment", "bool",
         "Vous engagez-vous à publier chaque mois vos ventes, vos dépenses et une photo du cahier ?",
         "هل تلتزم بنشر مبيعاتك ومصاريفك وصورة من الدفتر كل شهر؟", ALL, True, True, [],
         "Les rapports réguliers font monter votre score de confiance.", "التقارير المنتظمة ترفع درجة الثقة لديك."),
        ("accept_visits", "bool", "Acceptez-vous des visites annoncées de l'équipe Moucharaka ?",
         "هل تقبل زيارات معلنة من فريق مشاركة؟", ALL, True, True, [], "", ""),
    ]),
    ("Finances et dettes", "المالية والديون", [
        ("existing_debt", "money", "Total de vos dettes en cours (banque, microfinance, famille, fournisseurs)",
         "مجموع ديونك الحالية (بنك، تمويل أصغر، عائلة، موردون)", ALL, True, True, [], "En MRU. Indiquez 0 si aucune.",
         "بالأوقية الجديدة. اكتب 0 إن لم توجد."),
        ("monthly_debt_payment", "money", "Montant que vous remboursez chaque mois", "المبلغ الذي تسدده شهرياً",
         ALL, False, True, [], "", ""),
        ("main_bank", "text", "Votre banque principale", "بنكك الرئيسي", ALL, False, False, [], "", ""),
        ("mobile_money", "multi", "Comptes mobile money utilisés", "حسابات الدفع عبر الهاتف المستخدمة", ALL, False, True, [
            ("bankily", "Bankily", "بنكيلي"), ("masrvi", "Masrvi", "مصرفي"), ("sedad", "Sedad", "سداد"),
            ("click", "Click", "كليك"), ("none", "Aucun", "لا شيء")], "", ""),
        ("assets_owned", "textarea", "Biens que vous possédez (terrain, maison, voiture, bétail…)",
         "الممتلكات التي تملكها (أرض، منزل، سيارة، مواشٍ…)", ALL, False, False, [], "Confidentiel.", "سري."),
        ("contribution_source", "text", "D'où vient votre apport personnel ?", "من أين تأتي مساهمتك الشخصية؟",
         ALL, False, True, [], "", ""),
        ("stress_plan", "textarea", "Si vos ventes baissent de moitié pendant 3 mois, que faites-vous ?",
         "إذا انخفضت مبيعاتك إلى النصف لمدة 3 أشهر، ماذا ستفعل؟", ALL, True, True, [], "", ""),
    ]),
    ("Risques et engagements", "المخاطر والالتزامات", [
        ("main_risks", "textarea", "Les 3 principaux risques de votre projet et comment vous les limitez",
         "أهم 3 مخاطر لمشروعك وكيف تحدّ منها", ALL, True, True, [], "", ""),
        ("insured", "bool", "Vos biens ou marchandises sont-ils assurés ?", "هل ممتلكاتك أو بضائعك مؤمَّنة؟",
         ALL, False, True, [], "", ""),
        ("legal_disputes", "bool", "Avez-vous un litige en cours (justice, impôts, bail) ?",
         "هل لديك نزاع قائم (قضاء، ضرائب، إيجار)؟", ALL, True, False, [], "", ""),
        ("guarantor", "bool", "Une personne peut-elle se porter garante pour vous ?", "هل يمكن لشخص أن يكفلك؟",
         ALL, False, True, [], "", ""),
        ("sharia_commitment", "bool",
         "Acceptez-vous un financement sans intérêt (riba), où les pertes réelles sont partagées selon le contrat ?",
         "هل تقبل تمويلاً بلا فائدة (ربا)، تُقتسم فيه الخسائر الحقيقية حسب العقد؟", ALL, True, True, [], "", ""),
    ]),
    ("La boutique au quotidien", "الدكان يومياً", [
        ("boutique_why_location", "textarea", "Pourquoi avoir choisi cet emplacement ?", "لماذا اخترت هذا الموقع؟",
         B, True, True, [], "", ""),
        ("boutique_peak_hours", "text", "Heures de forte affluence", "ساعات الذروة", B, False, True, [],
         "Ex : 7h–9h et après la prière d'al-asr", "مثال: 7–9 صباحاً وبعد صلاة العصر"),
        ("boutique_best_month", "text", "Meilleure période de l'année et pourquoi", "أفضل فترة في السنة ولماذا",
         B, False, True, [], "", ""),
        ("boutique_stockouts", "choice", "Manquez-vous de marchandises faute d'argent ?",
         "هل تنفد منك البضائع بسبب نقص المال؟", B, True, True, [
             ("never", "Jamais", "أبداً"), ("sometimes", "Parfois", "أحياناً"), ("often", "Souvent", "غالباً")], "", ""),
        ("boutique_supplier_credit", "bool", "Vos fournisseurs vous font-ils crédit ?", "هل يمنحك الموردون ديناً؟",
         B, False, True, [], "", ""),
        ("boutique_supplier_days", "number", "Délai accordé par vos fournisseurs (jours)", "المهلة التي يمنحها الموردون (أيام)",
         B, False, True, [], "", ""),
        ("boutique_credit_policy", "textarea", "Comment gérez-vous le crédit aux clients (carnet) ?",
         "كيف تدير البيع بالدين للزبائن (الدفتر)؟", B, True, True, [], "", ""),
        ("boutique_losses", "bool", "Avez-vous subi des vols ou pertes de stock l'an dernier ?",
         "هل تعرضت لسرقة أو تلف في المخزون العام الماضي؟", B, False, True, [], "", ""),
        ("boutique_use", "multi", "Le financement servira surtout à…", "سيُستخدم التمويل أساساً في…", B, True, True, [
            ("stock", "Augmenter le stock", "زيادة المخزون"), ("new_products", "Ajouter des produits", "إضافة منتجات"),
            ("equipment", "Acheter de l'équipement", "شراء معدات"), ("renovation", "Rénover", "الترميم"),
            ("second_shop", "Ouvrir un 2e point de vente", "فتح نقطة بيع ثانية"),
            ("wholesale", "Passer au demi-gros", "الانتقال إلى نصف الجملة")], "", ""),
        ("boutique_family_premises", "bool", "Le local appartient-il à un membre de votre famille ?",
         "هل المحل ملك لأحد أفراد عائلتك؟", B, False, True, [], "", ""),
    ]),
    ("L'opération ponctuelle", "العملية الظرفية", [
        ("deal_price_source", "textarea", "Comment connaissez-vous le prix de revente ?", "كيف تعرف سعر إعادة البيع؟",
         D, True, True, [], "Prix du marché constatés, devis, contrat, bon de commande…",
         "أسعار السوق، عروض أسعار، عقد، طلب شراء…"),
        ("deal_storage", "textarea", "Où et comment la marchandise sera-t-elle stockée ?", "أين وكيف ستُخزَّن البضاعة؟",
         D, False, True, [], "", ""),
        ("deal_transport", "text", "Transport prévu", "النقل المتوقع", D, False, True, [], "", ""),
        ("deal_perishable", "bool", "La marchandise est-elle périssable ?", "هل البضاعة قابلة للتلف؟", D, True, True, [], "", ""),
        ("deal_customs", "bool", "Y a-t-il des droits de douane ou des autorisations à obtenir ?",
         "هل هناك رسوم جمركية أو تراخيص يجب الحصول عليها؟", D, False, True, [], "", ""),
        ("deal_worst_case", "textarea", "Si la revente prend du retard, comment payez-vous l'échéance ?",
         "إذا تأخر البيع، كيف ستسدد القسط؟", D, True, True, [], "", ""),
        ("deal_history", "textarea", "Résultats de vos opérations similaires précédentes", "نتائج عملياتك المماثلة السابقة",
         D, False, True, [], "", ""),
    ]),
    ("La future entreprise", "المؤسسة المستقبلية", [
        ("company_validation", "textarea", "Comment avez-vous vérifié que des clients achèteront ?",
         "كيف تأكدت من أن الزبائن سيشترون؟", C, True, True, [], "Pré-commandes, test, enquête, lettres d'intention…",
         "طلبات مسبقة، تجربة، استبيان، رسائل نوايا…"),
        ("company_first_customers", "number", "Clients ou pré-commandes déjà obtenus", "عدد الزبائن أو الطلبات المسبقة الحالية",
         C, False, True, [], "", ""),
        ("company_founders_invested", "money", "Montant déjà investi par les fondateurs (MRU)", "المبلغ الذي استثمره المؤسسون (أوقية)",
         C, True, True, [], "", ""),
        ("company_premises", "choice", "Local de l'entreprise", "مقر المؤسسة", C, False, True, [
            ("none", "Pas encore", "ليس بعد"), ("home", "À domicile", "في المنزل"), ("rented", "Loué", "مستأجر"),
            ("owned", "En propriété", "مملوك")], "", ""),
        ("company_suppliers", "bool", "Avez-vous des accords avec des fournisseurs ?", "هل لديك اتفاقات مع موردين؟",
         C, False, True, [], "", ""),
        ("company_dividends", "textarea", "Quand pensez-vous distribuer les premiers bénéfices ?",
         "متى تتوقع توزيع أول الأرباح؟", C, True, True, [], "", ""),
        ("company_governance", "textarea", "Comment les investisseurs seront-ils informés et consultés ?",
         "كيف سيتم إطلاع المستثمرين واستشارتهم؟", C, False, True, [], "", ""),
    ]),
    ("Impact", "الأثر", [
        ("jobs_now", "number", "Emplois aujourd'hui (vous compris)", "عدد الوظائف حالياً (بما فيها أنت)", ALL, False, True, [], "", ""),
        ("jobs_after", "number", "Emplois après le financement", "عدد الوظائف بعد التمويل", ALL, False, True, [], "", ""),
        ("women_youth", "bool", "Le projet emploie-t-il des femmes ou des jeunes ?", "هل يشغّل المشروع نساء أو شباباً؟",
         ALL, False, True, [], "", ""),
        ("local_sourcing", "choice", "Origine des produits ou matières premières", "مصدر المنتجات أو المواد الأولية",
         ALL, False, True, [("local", "Surtout mauritanienne", "موريتانية في الغالب"), ("mixed", "Mixte", "مختلطة"),
                            ("imported", "Surtout importée", "مستوردة في الغالب")], "", ""),
    ]),
]

SECTORS = [
    ("commerce", "Commerce de détail", "تجارة التجزئة"),
    ("wholesale", "Commerce de gros", "تجارة الجملة"),
    ("food", "Alimentation et restauration", "الأغذية والمطاعم"),
    ("livestock", "Élevage", "التنمية الحيوانية"),
    ("agriculture", "Agriculture", "الزراعة"),
    ("fishing", "Pêche", "الصيد"),
    ("construction", "BTP et matériaux", "البناء ومواد البناء"),
    ("transport", "Transport et logistique", "النقل واللوجستيك"),
    ("services", "Services", "الخدمات"),
    ("tech", "Numérique et télécoms", "الرقمنة والاتصالات"),
    ("health", "Santé et beauté", "الصحة والتجميل"),
    ("education", "Éducation", "التعليم"),
    ("energy", "Énergie solaire", "الطاقة الشمسية"),
    ("crafts", "Artisanat", "الصناعة التقليدية"),
    ("other", "Autre", "أخرى"),
]

# Business plan: commercial terms per use case (see docs/BUSINESS_PLAN.md)
FEE_POLICIES = [
    # kind, model, review_fee, success%, management%, min, max
    ("boutique", "moucharaka", 1500, 5, 10, 50_000, 3_000_000),
    ("boutique", "mourabaha", 1000, 3, 12, 30_000, 2_000_000),
    ("deal", "mourabaha", 1000, 2.5, 12, 30_000, 5_000_000),
    ("deal", "moucharaka", 1000, 3, 10, 30_000, 5_000_000),
    ("company", "moucharaka", 3000, 7, 8, 200_000, 10_000_000),
]


def load_all(apps):
    QuestionSection = apps.get_model("projects", "QuestionSection")
    Question = apps.get_model("projects", "Question")
    Sector = apps.get_model("projects", "Sector")
    FeePolicy = apps.get_model("projects", "FeePolicy")
    for order, (slug, fr, ar) in enumerate(SECTORS):
        Sector.objects.update_or_create(slug=slug, defaults={"name_fr": fr, "name_ar": ar, "order": order})
    for kind, model, review, success, mgmt, lo, hi in FEE_POLICIES:
        FeePolicy.objects.update_or_create(kind=kind, financing_model=model, defaults={
            "review_fee": review, "success_fee_pct": success, "management_fee_pct": mgmt,
            "min_target": lo, "max_target": hi})
    for s_order, (s_fr, s_ar, questions) in enumerate(SECTIONS):
        section, _c = QuestionSection.objects.update_or_create(title_fr=s_fr, defaults={"title_ar": s_ar, "order": s_order})
        for q_order, (code, typ, fr, ar, applies, required, public, choices, help_fr, help_ar) in enumerate(questions):
            Question.objects.update_or_create(code=code, defaults={
                "section": section, "type": typ, "text_fr": fr, "text_ar": ar, "applies_to": applies,
                "required": required, "is_public": public, "order": q_order, "help_fr": help_fr, "help_ar": help_ar,
                "choices": [{"value": v, "fr": f, "ar": a} for v, f, a in choices]})
