from django.db import models
from django.conf import settings
from products.models import Product

class RecommendationType(models.TextChoices):
    HIGHLY_RECOMMENDED = 'HR', 'Altamente Recomendado'
    RECOMMENDED = 'R', 'Recomendado'
    NOT_RECOMMENDED = 'NR', 'No Recomendado'

class UserPreference(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='user_preferences')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='user_preferences')
    rating = models.FloatField()
    category = models.CharField(max_length=100)
    weight = models.FloatField(default=1.0)
    created_at = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'user_preferences'
        unique_together = ('user', 'product')

class ProductRecommendation(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    score = models.FloatField()
    recommendation_type = models.CharField(
        max_length=10,
        choices=RecommendationType.choices,
        default=RecommendationType.RECOMMENDED
    )
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'product_recommendations'
        unique_together = ('user', 'product')
