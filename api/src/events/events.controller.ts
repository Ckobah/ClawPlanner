import { Body, Controller, Delete, Get, Param, Post, Query, Req, UseGuards } from '@nestjs/common';
import type { Request } from 'express';
import { AuthGuard } from '../auth/auth.guard';
import { CreateEventDto } from './dto/create-event.dto';
import { EventsService } from './events.service';

@UseGuards(AuthGuard)
@Controller('events')
export class EventsController {
  constructor(private readonly events: EventsService) {}

  @Get('month')
  async getMonth(@Req() req: Request, @Query('year') year: string, @Query('month') month: string) {
    const payload = req.user as { tg_id: number };
    return this.events.getMonth(payload.tg_id, parseInt(year, 10), parseInt(month, 10));
  }

  @Get('day')
  async getDay(@Req() req: Request, @Query('year') year: string, @Query('month') month: string, @Query('day') day: string) {
    const payload = req.user as { tg_id: number };
    return this.events.getDay(payload.tg_id, parseInt(year, 10), parseInt(month, 10), parseInt(day, 10));
  }

  @Post()
  async create(@Req() req: Request, @Body() dto: CreateEventDto) {
    const payload = req.user as { tg_id: number };
    return this.events.createEvent(payload.tg_id, dto);
  }

  @Delete(':id')
  async delete(@Req() req: Request, @Param('id') id: string, @Query('date') date?: string) {
    const payload = req.user as { tg_id: number };
    return this.events.deleteEvent(payload.tg_id, parseInt(id, 10), date);
  }
}
