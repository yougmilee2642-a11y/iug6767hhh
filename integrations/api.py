from fastapi import APIRouter, HTTPException
from integrations.settings import public_status, bindings
from integrations.booking import public_booking, decode, get_booking, CloudBookingRepository
from integrations.contracts import IntegrationError
from services.agent_service import AgentService
import storage


def router():
    api = APIRouter(prefix='/api/integrations', tags=['integrations'])

    @api.get('/status')
    def status():
        return public_status()

    @api.get('/bookings')
    def bookings_status():
        with storage.connect() as db:
            return {'bookings': [public_booking(decode(row)) for row in db.execute(
                'SELECT * FROM cloud_bookings ORDER BY created_at DESC LIMIT 100')]}

    @api.post('/bookings/{booking_id}/reconcile')
    def reconcile(booking_id: str):
        row = get_booking(booking_id)
        if row is None:
            raise HTTPException(404, 'Запись не найдена.')
        try:
            binding = bindings().get(row['agent_id'])
            if binding is None: raise IntegrationError('config')
            config = AgentService().resolve(row['agent_id'])
            result = CloudBookingRepository(config.id, binding, config.business).sync(booking_id)
            return public_booking(result)
        except IntegrationError as exc:
            raise HTTPException(409 if exc.code in ('busy', 'conflict') else 503, str(exc)) from None
        except (LookupError, ValueError):
            raise HTTPException(409, 'Исходный агент недоступен. Нужна проверка владельцем.') from None

    return api
