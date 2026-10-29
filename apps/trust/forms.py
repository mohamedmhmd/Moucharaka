from django import forms

from .models import Review

STARS = [(i, str(i)) for i in range(5, 0, -1)]


class ReviewForm(forms.ModelForm):
    class Meta:
        model = Review
        fields = ["communication", "transparency", "commitments", "comment"]
        widgets = {
            "communication": forms.RadioSelect(choices=STARS, attrs={"class": "stars"}),
            "transparency": forms.RadioSelect(choices=STARS, attrs={"class": "stars"}),
            "commitments": forms.RadioSelect(choices=STARS, attrs={"class": "stars"}),
            "comment": forms.Textarea(attrs={"rows": 3}),
        }
