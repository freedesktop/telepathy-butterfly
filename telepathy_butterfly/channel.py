# telepathy-butterfly - an MSN connection manager for Telepathy
#
# Copyright (C) 2006-2007 Ali Sabil <ali.sabil@gmail.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

import time
import logging
from gettext import gettext as _
import weakref

import telepathy
import pymsn
import pymsn.event
import gobject

__all__ = ['ButterflySubscribeListChannel', 'ButterflyPublishListChannel',
        'ButterflyTextChannel']

class ButterflyListChannel(
        telepathy.server.ChannelTypeContactList,
        telepathy.server.ChannelInterfaceGroup):

    def __init__(self, connection, handle):
        telepathy.server.ChannelTypeContactList.__init__(self,
                connection, handle)
        telepathy.server.ChannelInterfaceGroup.__init__(self)
        gobject.idle_add(self.__populate, connection)

    def __populate(self, connection):
        for contact in connection._pymsn_client.address_book.contacts:
            full_account = "/".join([contact.account, str(contact.network_id)])
            handle = connection._handle_manager.handle_for_contact(full_account)
            self.contact_added(handle, contact)
        return False

    def contact_added(self, handle, contact):
        pass



class ButterflySubscribeListChannel(ButterflyListChannel):

    def __init__(self, connection, handle):
        ButterflyListChannel.__init__(self, connection, handle)
        self.GroupFlagsChanged(0, 0) # no contact Management for now

    def contact_added(self, handle, contact):
        added = set()
        if contact.is_member(pymsn.Membership.FORWARD):
            added.add(handle)

        if added:
            self.MembersChanged('', added, (), (), (), 0,
                                telepathy.CHANNEL_GROUP_CHANGE_REASON_NONE)

class ButterflyPublishListChannel(ButterflyListChannel):

    def __init__(self, connection, handle):
        ButterflyListChannel.__init__(self, connection, handle)
        self.GroupFlagsChanged(0, 0) # no contact Management for now

    def contact_added(self, handle, contact):
        added = set()
        local_pending = set()

        if contact.is_member(pymsn.Membership.REVERSE):
            added.add(handle)

        if contact.is_member(pymsn.Membership.PENDING):
            local_pending.add(handle)

        if added:
            self.MembersChanged('', added, (), local_pending, (), 0,
                                telepathy.CHANNEL_GROUP_CHANGE_REASON_NONE)

class ConversationEventForwarder(pymsn.event.ConversationEventInterface):
    """Used for forwarding events to ButterflyTextChannel so that it doesn't
    have to subclass ConversationEventInterface, which would create circular
    references"""
    def __init__(self, conversation, text_channel):
        self._text_channel = weakref.proxy(text_channel)
        pymsn.event.ConversationEventInterface.__init__(self, conversation)
        
    def on_conversation_user_joined(self, contact):
        self._text_channel.on_conversation_user_joined(contact)
    def on_conversation_user_left(self, contact):
        self._text_channel.on_conversation_user_left(contact)
    def on_conversation_message_received(self, *args):
        self._text_channel.on_conversation_message_received(*args)    
    def on_conversation_nudge_received(self, sender):
        self._text_channel.on_conversation_nudge_received(sender)

class ButterflyTextChannel(
        telepathy.server.ChannelTypeText,
        telepathy.server.ChannelInterfaceGroup):
    
    logger = logging.getLogger('telepathy-butterfly:text-channel')

    def __init__(self, connection, conversation=None, contacts=[]):
        self._recv_id = 0
        telepathy.server.ChannelTypeText.__init__(self, connection, None)
        telepathy.server.ChannelInterfaceGroup.__init__(self)
        self.GroupFlagsChanged(telepathy.CHANNEL_GROUP_FLAG_CAN_ADD, 0)
        if conversation is None:
            self._conversation = pymsn.Conversation(connection._pymsn_client,
                    contacts)
        else:
            self._conversation = conversation 
            gobject.idle_add(self.__add_initial_participants)
        # Forwarder is kept alive by conversation, and holds a weakref to self.
        # Ugly, I know.
        ConversationEventForwarder(self._conversation, self)

    def __add_initial_participants(self):
        handles = []
        for participant in self._conversation.participants:
            full_account = "/".join([participant.account, str(participant.network_id)])
            handle = self._conn._handle_manager.handle_for_contact(full_account)
            handles.append(handle)
        self.MembersChanged('', handles, [], [], [],
                0, telepathy.CHANNEL_GROUP_CHANGE_REASON_INVITED)
        return False

    def on_conversation_user_joined(self, contact):
        full_account = "/".join([contact.account, str(contact.network_id)])
        self.logger.debug("user joined : %s" % full_account)
        handle = self._conn._handle_manager.handle_for_contact(full_account)
        self.MembersChanged('', [handle], [], [], [],
                handle, telepathy.CHANNEL_GROUP_CHANGE_REASON_INVITED)

    def on_conversation_user_left(self, contact):
        full_account = "/".join([contact.account, str(contact.network_id)])
        self.logger.debug("user left : %s" % full_account)
        handle = self._conn._handle_manager.handle_for_contact(full_account)
        self.MembersChanged('', [], [handle], [], [],
                handle, telepathy.CHANNEL_GROUP_CHANGE_REASON_NONE)

    def on_conversation_message_received(self, sender, message, formatting):
        id = self._recv_id
        timestamp = int(time.time())
        full_account = "/".join([sender.account, str(sender.network_id)])
        sender = self._conn._handle_manager.handle_for_contact(full_account)
        type = telepathy.CHANNEL_TEXT_MESSAGE_TYPE_NORMAL

        self.Received(id, timestamp, sender, type, 0, message)
        self._recv_id += 1
    
    def on_conversation_nudge_received(self, sender):
        id = self._recv_id
        timestamp = int(time.time())
        full_account = "/".join([sender.account, str(sender.network_id)])
        sender = self._conn._handle_manager.handle_for_contact(full_account)
        type = telepathy.CHANNEL_TEXT_MESSAGE_TYPE_ACTION
        text = unicode(_("sends you a nudge"), "utf-8")

        self.Received(id, timestamp, sender, type, 0, text)
        self._recv_id += 1
    
    def Send(self, message_type, text):
        if message_type == telepathy.CHANNEL_TEXT_MESSAGE_TYPE_NORMAL:
            self._conversation.send_text_message(text)
        elif message_type == telepathy.CHANNEL_TEXT_MESSAGE_TYPE_ACTION and \
                text == u"nudge":
            self._conversation.send_nudge()
        else:
            raise telepathy.NotImplemented("Unhandled message type")
        self.Sent(int(time.time()), message_type, text) 

    def Close(self):
        for handle, channel in self._conn._channel_manager.\
                _text_channels.items():
            if channel is self:
                del self._conn._channel_manager._text_channels[handle]
        #FIXME: find out why this isn't working
        self._conversation.leave()
        telepathy.server.ChannelTypeText.Close(self)
        self.remove_from_connection()
