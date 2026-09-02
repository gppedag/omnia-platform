from __future__ import annotations
from datetime import datetime, timezone
from urllib.parse import quote
import httpx
from app.config import settings

async def _google_token():
    if not settings.GOOGLE_CALENDAR_CLIENT_ID or not settings.GOOGLE_CALENDAR_CLIENT_SECRET or not settings.GOOGLE_CALENDAR_REFRESH_TOKEN:
        raise RuntimeError('Credenziali Google Calendar incomplete')
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post('https://oauth2.googleapis.com/token', data={
            'client_id': settings.GOOGLE_CALENDAR_CLIENT_ID,
            'client_secret': settings.GOOGLE_CALENDAR_CLIENT_SECRET,
            'refresh_token': settings.GOOGLE_CALENDAR_REFRESH_TOKEN,
            'grant_type': 'refresh_token',
        })
        r.raise_for_status()
        return r.json()['access_token']

async def _ms_token():
    if not settings.M365_TENANT_ID or not settings.M365_CLIENT_ID or not settings.M365_CLIENT_SECRET:
        raise RuntimeError('Credenziali Microsoft 365 incomplete')
    url = f'https://login.microsoftonline.com/{settings.M365_TENANT_ID}/oauth2/v2.0/token'
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(url, data={
            'client_id': settings.M365_CLIENT_ID,
            'client_secret': settings.M365_CLIENT_SECRET,
            'scope': 'https://graph.microsoft.com/.default',
            'grant_type': 'client_credentials',
        })
        r.raise_for_status()
        return r.json()['access_token']

async def test_provider(provider: str):
    if provider == 'google':
        token = await _google_token()
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get('https://www.googleapis.com/calendar/v3/users/me/calendarList', headers={'Authorization': f'Bearer {token}'})
            return {'ok': r.is_success, 'message': f'Google Calendar HTTP {r.status_code}'}
    if provider == 'microsoft365':
        token = await _ms_token()
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get('https://graph.microsoft.com/v1.0/users?$top=1', headers={'Authorization': f'Bearer {token}'})
            return {'ok': r.is_success, 'message': f'Microsoft Graph HTTP {r.status_code}'}
    return {'ok': False, 'message': 'Provider non riconosciuto'}

async def upsert_event(booking, patient, doctors):
    """Sincronizza l'appuntamento sul calendario del primo medico configurato.
    Ritorna provider/event_id. I medici aggiuntivi vengono inseriti come partecipanti.
    """
    target = next((d for d in doctors if d.external_provider in {'google','microsoft365'} and (d.external_calendar_id or d.external_calendar_user)), None)
    if not target:
        return None
    end_at = booking.end_at or booking.scheduled_at
    attendees = [d.email for d in doctors if d.email]
    title = f'CUP - {booking.service_name}'
    desc = f'Prenotazione CUP #{booking.id}' + (f' - {patient.full_name}' if patient and patient.full_name else '')
    if booking.notes:
        desc += f'\nNote: {booking.notes}'

    if target.external_provider == 'google':
        token = await _google_token()
        cal = target.external_calendar_id or 'primary'
        base = f'https://www.googleapis.com/calendar/v3/calendars/{quote(cal, safe="")}/events'
        payload = {
            'summary': title, 'description': desc,
            'start': {'dateTime': booking.scheduled_at.isoformat(), 'timeZone': 'Europe/Rome'},
            'end': {'dateTime': end_at.isoformat(), 'timeZone': 'Europe/Rome'},
            'attendees': [{'email': x} for x in attendees],
        }
        async with httpx.AsyncClient(timeout=20) as client:
            if booking.external_provider == 'google' and booking.external_event_id:
                url = base + '/' + booking.external_event_id
                r = await client.put(url, headers={'Authorization': f'Bearer {token}'}, json=payload)
            else:
                r = await client.post(base, headers={'Authorization': f'Bearer {token}'}, json=payload)
            r.raise_for_status()
            return ('google', r.json().get('id'))

    token = await _ms_token()
    user = target.external_calendar_user or target.email
    if not user:
        raise RuntimeError('Per Microsoft 365 indicare utente/mailbox del medico')
    cal = target.external_calendar_id
    if cal:
        base = f'https://graph.microsoft.com/v1.0/users/{user}/calendars/{cal}/events'
    else:
        base = f'https://graph.microsoft.com/v1.0/users/{user}/events'
    payload = {
        'subject': title,
        'body': {'contentType': 'text', 'content': desc},
        'start': {'dateTime': booking.scheduled_at.strftime('%Y-%m-%dT%H:%M:%S'), 'timeZone': 'Europe/Rome'},
        'end': {'dateTime': end_at.strftime('%Y-%m-%dT%H:%M:%S'), 'timeZone': 'Europe/Rome'},
        'attendees': [{'emailAddress': {'address': x}, 'type': 'required'} for x in attendees],
    }
    async with httpx.AsyncClient(timeout=20) as client:
        headers={'Authorization': f'Bearer {token}'}
        if booking.external_provider == 'microsoft365' and booking.external_event_id:
            r = await client.patch(base + '/' + booking.external_event_id, headers=headers, json=payload)
            r.raise_for_status()
            return ('microsoft365', booking.external_event_id)
        r = await client.post(base, headers=headers, json=payload)
        r.raise_for_status()
        return ('microsoft365', r.json().get('id'))

async def delete_event(booking, doctors):
    if not booking.external_provider or not booking.external_event_id:
        return
    target = next((d for d in doctors if d.external_provider == booking.external_provider), None)
    if not target:
        return
    try:
        if booking.external_provider == 'google':
            token = await _google_token()
            cal = target.external_calendar_id or 'primary'
            url = f'https://www.googleapis.com/calendar/v3/calendars/{quote(cal, safe="")}/events/{quote(booking.external_event_id, safe="")}'
            async with httpx.AsyncClient(timeout=15) as client:
                await client.delete(url, headers={'Authorization': f'Bearer {token}'})
        elif booking.external_provider == 'microsoft365':
            token = await _ms_token()
            user = target.external_calendar_user or target.email
            cal = target.external_calendar_id
            base = f'https://graph.microsoft.com/v1.0/users/{user}/calendars/{cal}/events' if cal else f'https://graph.microsoft.com/v1.0/users/{user}/events'
            async with httpx.AsyncClient(timeout=15) as client:
                await client.delete(base + '/' + booking.external_event_id, headers={'Authorization': f'Bearer {token}'})
    except Exception:
        pass
