import { CalendarDays } from "lucide-react";

export default function Bookings() {
  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center gap-2 px-5 py-4 border-b border-slate-800">
        <CalendarDays size={16} className="text-blue-400" />
        <h2 className="text-sm font-semibold text-white">Bookings</h2>
      </div>
      <div className="flex-1 overflow-y-auto px-5 py-4">
        <div className="space-y-3 max-w-lg">
          <div className="p-3 bg-slate-900/50 border border-slate-800 rounded-lg">
            <p className="text-sm text-white">Appointments</p>
            <p className="text-xs text-slate-500 mt-0.5">Schedule and manage meetings</p>
          </div>
          <div className="p-3 bg-slate-900/50 border border-slate-800 rounded-lg">
            <p className="text-sm text-white">Hotel Reservations</p>
            <p className="text-xs text-slate-500 mt-0.5">Search and book accommodations</p>
          </div>
          <div className="p-3 bg-slate-900/50 border border-slate-800 rounded-lg">
            <p className="text-sm text-white">Tickets</p>
            <p className="text-xs text-slate-500 mt-0.5">Flights, trains, events</p>
          </div>
          <div className="p-3 bg-slate-900/50 border border-slate-800 rounded-lg">
            <p className="text-sm text-white">Restaurants</p>
            <p className="text-xs text-slate-500 mt-0.5">Table reservations and food orders</p>
          </div>
        </div>
      </div>
    </div>
  );
}
