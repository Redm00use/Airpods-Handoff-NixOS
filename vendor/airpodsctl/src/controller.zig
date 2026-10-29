const aacp = @import("aacp");
const battery = @import("battery");
const command = @import("command");
const control_command = @import("control_command");
const noise_control = @import("noise_control");
const smart_routing = @import("smart_routing");
const support = @import("support");
const wear_detection = @import("wear_detection");

pub const Error = aacp.Error || error{PolicyDenied};

pub const State = struct {
    listening_mode: ?noise_control.Mode = null,
    listening_mode_generation: u64 = 0,
    battery: battery.Report = .{},
    battery_generation: u64 = 0,
    wear: ?wear_detection.WearReport = null,
    wear_generation: u64 = 0,
    routing: smart_routing.State = .{},
    routing_generation: u64 = 0,
    audio_source_generation: u64 = 0,
    connected_devices_generation: u64 = 0,
    ownership_generation: u64 = 0,
    relay_generation: u64 = 0,
};

pub const Event = union(enum) {
    listening_mode: noise_control.Mode,
    battery: battery.Report,
    wear: wear_detection.WearReport,
    routing: smart_routing.Status,
    routing_relay: smart_routing.Relay,
    release_requested: void,
};

fn ignoreEvent(_: ?*anyopaque, _: Event) void {}

pub const EventObserver = struct {
    context: ?*anyopaque = null,
    callback: *const fn (?*anyopaque, Event) void = ignoreEvent,

    pub fn notify(self: EventObserver, event: ?Event) void {
        if (event) |value| self.callback(self.context, value);
    }
};

fn loggedEvent(event: Event) Event {
    switch (event) {
        .listening_mode => |mode| support.log(
            .debug,
            "The listening mode is now '{s}'.",
            .{mode.name()},
        ),
        .battery => |report| {
            if (report.left) |reading| support.log(
                .debug,
                "The left earbud reports {d}% and {s}.",
                .{ reading.level, reading.state.name() },
            );
            if (report.right) |reading| support.log(
                .debug,
                "The right earbud reports {d}% and {s}.",
                .{ reading.level, reading.state.name() },
            );
        },
        .wear => |report| support.log(
            .debug,
            "The wear state is primary '{s}', secondary '{s}'.",
            .{ report.primary.name(), report.secondary.name() },
        ),
        .routing => |status| support.log(
            .debug,
            "Routing is '{s}', hosts '{s}', owner '{s}', remote activity '{s}'.",
            .{
                status.multipointName(),
                status.hosts.name(),
                status.owner.name(),
                status.remote_activity.name(),
            },
        ),
        .release_requested => support.log(.info, "Received an explicit request to yield audio ownership from the AirPods routing channel.", .{}),
        .routing_relay => |message| support.log(
            .debug,
            "Received an AirPods smart-routing relay '{s}' message with a {d}-byte opaque payload.",
            .{ message.opcode.name(), message.payload.len },
        ),
    }
    return event;
}

pub const Controller = struct {
    session: aacp.Session,
    local_address: ?smart_routing.Address = null,
    state: State = .{},

    pub fn receiveOne(self: *Controller) Error!?Event {
        const packet = try self.session.receive();
        support.log(.debug, "AACP frame length={d}, opcode={x}", .{packet.len, if (packet.len >= 6) @as(u16, packet[4]) | (@as(u16, packet[5]) << 8) else @as(u16, 0xffff)});

        if (smart_routing.isReleaseRequest(packet)) return loggedEvent(.{ .release_requested = {} });
        if (control_command.parsePacket(packet) catch {
            self.session.channel.failure.set("AirPods returned an invalid control-command response", .{});
            return error.ProtocolFailure;
        }) |control_state| {
            if (noise_control.parseCommand(control_state) catch {
                self.session.channel.failure.set("AirPods returned an invalid listening-mode response", .{});
                return error.ProtocolFailure;
            }) |mode| {
                self.state.listening_mode = mode;
                self.state.listening_mode_generation +%= 1;
                return loggedEvent(.{ .listening_mode = mode });
            }
            if (smart_routing.parseOwnership(control_state) catch {
                self.session.channel.failure.set("AirPods returned an invalid routing-ownership response", .{});
                return error.ProtocolFailure;
            }) |owns| {
                self.state.routing.updateOwnership(owns);
                self.state.ownership_generation +%= 1;
                self.state.routing_generation +%= 1;
                return loggedEvent(.{ .routing = self.state.routing.status() });
            }
            return null;
        }
        if (smart_routing.parsePacket(packet) catch {
            // Relay envelopes vary by firmware and are not used to authorize routing.
            // Ignore unsupported receive envelopes without invalidating the transport.
            if (packet.len >= 6 and packet[4] == 0x11 and packet[5] == 0) {
                support.log(.warn, "Ignored an unsupported relay envelope of {d} bytes; routing state was not changed", .{packet.len});
                return null;
            }
            self.session.channel.failure.set("AirPods returned an invalid smart-routing response", .{});
            return error.ProtocolFailure;
        }) |routing_packet| {
            switch (routing_packet) {
                .audio_source => |source| if (self.local_address) |local| {
                    self.state.routing.updateAudioSource(source, local);
                    self.state.audio_source_generation +%= 1;
                },
                .connected_devices => |devices| {
                    if (self.local_address) |local| {
                        self.state.routing.updateConnectedDevices(devices, local);
                    }
                    self.state.connected_devices_generation +%= 1;
                },
                .relay => |message| {
                    self.state.relay_generation +%= 1;
                    return loggedEvent(.{ .routing_relay = message });
                },
            }
            self.state.routing_generation +%= 1;
            return loggedEvent(.{ .routing = self.state.routing.status() });
        }
        if (wear_detection.parseWearPacket(packet) catch {
            self.session.channel.failure.set("AirPods returned an invalid wear-state response", .{});
            return error.ProtocolFailure;
        }) |report| {
            self.state.wear = report;
            self.state.wear_generation +%= 1;
            return loggedEvent(.{ .wear = report });
        }
        if (battery.parsePacket(packet) catch {
            self.session.channel.failure.set("AirPods returned an invalid battery response", .{});
            return error.ProtocolFailure;
        }) |report| {
            // A notification may contain only one earbud, so preserve the other cached reading.
            if (report.left) |reading| self.state.battery.left = reading;
            if (report.right) |reading| self.state.battery.right = reading;
            if (report.left != null or report.right != null) {
                self.state.battery_generation +%= 1;
                return loggedEvent(.{ .battery = report });
            }
        }
        return null;
    }

    fn receiveObserved(self: *Controller, observer: EventObserver) Error!void {
        observer.notify(try self.receiveOne());
    }

    fn refreshRouting(self: *Controller, observer: EventObserver) Error!smart_routing.Status {
        if (self.local_address == null) {
            self.session.channel.failure.set("cannot determine the local Bluetooth address for switching", .{});
            return error.ProtocolFailure;
        }

        const previous_audio_source_generation = self.state.audio_source_generation;
        const previous_connected_devices_generation = self.state.connected_devices_generation;
        try smart_routing.requestStatus(&self.session);
        while (self.state.audio_source_generation == previous_audio_source_generation or
            self.state.connected_devices_generation == previous_connected_devices_generation)
        {
            try self.receiveObserved(observer);
        }
        return self.state.routing.status();
    }

    fn runSwitching(
        self: *Controller,
        request: command.Switching,
        observer: EventObserver,
    ) Error!command.Result {
        var status = try self.refreshRouting(observer);
        switch (request.action) {
            .status => return .{ .switching = status },
            .take, .take_media => {
                if (status.hosts != .local_and_remote) {
                    self.session.channel.failure.set(
                        "AirPods multipoint is not ready; connect the iPhone and verify the BlueZ DeviceID setup",
                        .{},
                    );
                    return error.PolicyDenied;
                }
                if (request.action == .take_media and !self.state.routing.allowsMediaTake()) {
                    self.session.channel.failure.set("media takeover denied: fresh source is a call, unknown, or multipoint unavailable", .{});
                    return error.PolicyDenied;
                }
                if (self.state.routing.confirmed_owns == true) return .{ .switching = status };
                if (request.force and status.owner == .linux) return .{ .switching = status };
                if (!request.force and request.action != .take_media and (status.owner == .unknown or status.remote_activity != .idle)) {
                    self.session.channel.failure.set(
                        "remote AirPods activity is not confirmed idle; use switching take --force to override it",
                        .{},
                    );
                    return error.PolicyDenied;
                }
            },
            .release => {
                if (self.state.routing.confirmed_owns == false or
                    (self.state.routing.confirmed_owns == null and
                        (status.owner == .remote or status.owner == .none)))
                {
                    return .{ .switching = status };
                }
                if (status.owner == .unknown) {
                    self.session.channel.failure.set("AirPods routing ownership is unknown", .{});
                    return error.PolicyDenied;
                }
            },
        }

        const target_owns = request.action == .take or request.action == .take_media;
        const previous_generation = self.state.ownership_generation;
        try smart_routing.setOwnership(&self.session, target_owns);

        // An unconfirmed release is idempotent: no notification is emitted when owns=0 was already set.
        if (!target_owns and self.state.routing.confirmed_owns == null) {
            self.state.routing.updateOwnership(false);
            return .{ .switching = self.state.routing.status() };
        }
        while (self.state.ownership_generation == previous_generation or
            self.state.routing.confirmed_owns == null or
            self.state.routing.confirmed_owns.? != target_owns)
        {
            self.receiveObserved(observer) catch |failure| {
                self.session.channel.failure.set(
                    "AirPods did not acknowledge switching ownership {s} before the timeout",
                    .{if (target_owns) "take" else "release"},
                );
                return failure;
            };
        }
        status = self.state.routing.status();
        return .{ .switching = status };
    }

    pub fn requestRoutingStatus(self: *Controller, deadline_ms: i64) Error!void {
        self.session.channel.deadline_ms = deadline_ms;
        try smart_routing.requestStatus(&self.session);
    }

    pub fn runWithObserver(
        self: *Controller,
        operation: command.Operation,
        deadline_ms: i64,
        observer: EventObserver,
    ) Error!command.Result {
        self.session.channel.deadline_ms = deadline_ms;

        return switch (operation) {
            .noise_control => |request| result: {
                while (self.state.listening_mode == null) try self.receiveObserved(observer);
                const final_mode = noise_control.targetMode(
                    request.action,
                    self.state.listening_mode.?,
                    request.toggle_modes[0..request.toggle_mode_count],
                );
                if (request.action != .status) {
                    const previous_generation = self.state.listening_mode_generation;
                    try noise_control.setMode(&self.session, final_mode);

                    // A newer matching event is the acknowledgement; cached state cannot confirm a write.
                    while (self.state.listening_mode_generation == previous_generation or
                        self.state.listening_mode.? != final_mode)
                    {
                        self.receiveObserved(observer) catch |failure| {
                            if (self.state.listening_mode_generation != previous_generation) {
                                self.session.channel.failure.set(
                                    "AirPods did not acknowledge {s}; the last reported mode was {s}",
                                    .{ final_mode.name(), self.state.listening_mode.?.name() },
                                );
                            }
                            return failure;
                        };
                    }
                }
                break :result .{ .mode = final_mode };
            },
            .battery => |component| .{ .battery = .{
                .component = component,
                .report = if ((component == null and self.state.battery_generation != 0) or
                    (component != null and self.state.battery.get(component.?) != null))
                    self.state.battery
                else report: {
                    var saw_report = self.state.battery_generation != 0;

                    while (component == null or self.state.battery.get(component.?) == null) {
                        self.receiveObserved(observer) catch |failure| {
                            if (saw_report and component != null) {
                                self.session.channel.failure.set(
                                    "AirPods did not report the {s} battery before the timeout",
                                    .{component.?.name()},
                                );
                            }
                            return failure;
                        };
                        saw_report = saw_report or self.state.battery_generation != 0;
                        if (component == null and saw_report) break;
                    }
                    break :report self.state.battery;
                },
            } },
            .wear_status => result: {
                while (self.state.wear == null) try self.receiveObserved(observer);
                break :result .{ .wear_status = self.state.wear.? };
            },
            .switching => |request| try self.runSwitching(request, observer),
        };
    }

    pub fn run(self: *Controller, operation: command.Operation, deadline_ms: i64) Error!command.Result {
        return self.runWithObserver(operation, deadline_ms, .{});
    }
};
