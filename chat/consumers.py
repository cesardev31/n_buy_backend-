import json
import os
import uuid
from channels.generic.websocket import AsyncWebsocketConsumer
import google.generativeai as genai
from asgiref.sync import sync_to_async
from .models import ChatSession, ChatMessage
from products.models import Product, Sale, Inventory
from django.conf import settings
from channels.auth import login
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth import get_user_model
from channels.db import database_sync_to_async
from recommendations.recommendation_engine import RecommendationEngine
from recommendations.models import ProductRecommendation, UserPreference

User = get_user_model()

class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        # Generar un ID único para la sesión
        self.session_id = str(uuid.uuid4())
        self.recommendation_engine = RecommendationEngine()
        
        # Verificar y configurar Google AI
        if not hasattr(settings, 'GOOGLE_API_KEY') or not settings.GOOGLE_API_KEY:
            print("Error: GOOGLE_API_KEY no está configurada en settings")
            await self.close()
            return
            
        genai.configure(api_key=settings.GOOGLE_API_KEY)

        self.room_name = f"session_{self.session_id}"
        self.room_group_name = f"chat_{self.room_name}"

        # Unirse al grupo de chat
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()

        # Mensaje de bienvenida simple sin recomendaciones personalizadas
        welcome_message = (
            f"👋 ¡Hola! Soy el asistente virtual de Buy n Large.\n\n"
            "Te puedo ayudar con:\n"
            "🔍 • Buscar productos específicos\n"
            "📦 • Consultar disponibilidad y precios\n"
            "❓ • Responder tus dudas sobre nuestros productos\n\n"
            "¿En qué puedo ayudarte hoy?"
        )
        
        await self.send(text_data=json.dumps({
            "message": welcome_message,
            "is_bot": True,
            "name": "Buy n Large",
            "is_admin": False
        }))

    async def disconnect(self, close_code):
        # Dejar el grupo de chat
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )

    async def receive(self, text_data):
        try:
            text_data_json = json.loads(text_data)
            message = text_data_json["message"]
            user_name = text_data_json.get("name", "Usuario")
            is_admin = text_data_json.get("is_admin", False)

            # Guardar mensaje del usuario
            await database_sync_to_async(ChatMessage.objects.create)(
                anonymous_session_id=self.session_id,
                content=message,
                is_user=True
            )

            # Enviar mensaje del usuario al grupo
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "chat_message",
                    "message": message,
                    "is_bot": False,
                    "is_typing": False,
                    "name": user_name,
                    "is_admin": is_admin
                }
            )

            # Enviar indicador de "escribiendo..."
            await self.send(text_data=json.dumps({
                "message": "⌛ Procesando tu solicitud...",
                "is_bot": True,
                "is_typing": True,
                "name": "Bot",
                "is_admin": True
            }))

            # Procesar con Google AI
            response = await self.process_with_ai(message, user_name, is_admin)

            # Guardar respuesta del bot
            await database_sync_to_async(ChatMessage.objects.create)(
                anonymous_session_id=self.session_id,
                content=response,
                is_user=False
            )

            # Enviar respuesta final
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    "type": "chat_message",
                    "message": response,
                    "is_bot": True,
                    "is_typing": False,
                    "name": "Bot",
                    "is_admin": True
                }
            )
        except Exception as e:
            print(f"Error en receive: {str(e)}")
            error_message = f"❌ Lo siento, hubo un error al procesar tu mensaje: {str(e)}"
            await self.send(text_data=json.dumps({
                "message": error_message,
                "is_bot": True,
                "is_typing": False,
                "name": "Bot",
                "is_admin": True
            }))

    async def chat_message(self, event):
        try:
            message = event["message"]
            is_bot = event["is_bot"]
            is_typing = event.get("is_typing", False)
            name = event.get("name", "Usuario")
            is_admin = event.get("is_admin", False)

            await self.send(text_data=json.dumps({
                "message": message,
                "is_bot": is_bot,
                "is_typing": is_typing,
                "name": name,
                "is_admin": is_admin
            }))
        except Exception as e:
            print(f"Error en chat_message: {str(e)}")

    async def process_with_ai(self, message, user_name, is_admin):
        try:
            # Obtener datos del sistema para contexto
            products = await sync_to_async(list)(Product.objects.all())
            inventories = await sync_to_async(list)(Inventory.objects.all())
            
            # Crear listas de productos por tipo de recomendación
            recommended_products = {
                'high': [],
                'medium': [],
                'low': []
            }
            
            for product in products:
                recommended_products['low'].append({
                    'name': product.name,
                    'price': float(product.current_price),
                    'brand': product.brand,
                    'category': product.category,
                    'stock': next((inv.quantity for inv in inventories if inv.product_id == product.id), 0)
                })

            # Crear contexto con datos reales
            system_context = f"""
            Información del usuario:
            👤 Nombre: {user_name}
            🔑 Rol: {'Administrador' if is_admin else 'Cliente'}
            
            Catálogo actual:
            📦 Total de productos: {len(products)}
            
            ✅ Productos Altamente Recomendados:
            {self._format_product_list(recommended_products['high'])}
            
            🔹 Productos Recomendados:
            {self._format_product_list(recommended_products['medium'])}
            
            ❌ Otros Productos:
            {self._format_product_list(recommended_products['low'])}
            """

            # Configurar el modelo
            model = genai.GenerativeModel('gemini-pro')
            
            # Crear el prompt
            prompt = f"""
            Eres el asistente virtual de Buy n Large, una tienda de tecnología.
            Tu objetivo es ayudar a los usuarios a encontrar los productos perfectos para ellos.
            
            Reglas importantes:
            1. Sé amigable y profesional
            2. Usa emojis para hacer la conversación más agradable
            3. Cuando menciones precios, siempre usa el formato $X.XX
            4. Si un producto tiene descuento, destácalo
            5. Si un producto tiene poco stock (menos de 5 unidades), mencionarlo
            6. Siempre sugiere productos relacionados
            7. Para administradores, incluye información de ventas y stock
            8. Para clientes, enfócate en beneficios y características
            
            Contexto del sistema:
            {system_context}
            
            Mensaje del usuario:
            {message}
            """

            # Generar respuesta
            response = model.generate_content(prompt)
            return response.text

        except Exception as e:
            print(f"Error en process_with_ai: {str(e)}")
            return f"❌ Lo siento, hubo un error al procesar tu mensaje: {str(e)}"

    def _format_product_list(self, products):
        if not products:
            return "Ninguno disponible"
        
        return "\n".join([
            f"• {p['name']} ({p['brand']}) - ${p['price']:.2f} - {p['stock']} unidades disponibles"
            for p in products
        ])