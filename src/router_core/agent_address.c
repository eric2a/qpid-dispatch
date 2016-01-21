/*
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements.  See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership.  The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License.  You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing,
 * software distributed under the License is distributed on an
 * "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
 * KIND, either express or implied.  See the License for the
 * specific language governing permissions and limitations
 * under the License.
 */

#include "agent_address.h"
#include "router_core_private.h"

#define QDR_ADDRESS_NAME                      0
#define QDR_ADDRESS_IDENTITY                  1
#define QDR_ADDRESS_TYPE                      2
#define QDR_ADDRESS_KEY                       3
#define QDR_ADDRESS_IN_PROCESS                4
#define QDR_ADDRESS_SUBSCRIBER_COUNT          5
#define QDR_ADDRESS_REMOTE_COUNT              6
#define QDR_ADDRESS_HOST_ROUTERS              7
#define QDR_ADDRESS_DELIVERIES_INGRESS        8
#define QDR_ADDRESS_DELIVERIES_EGRESS         9
#define QDR_ADDRESS_DELIVERIES_TRANSIT        10
#define QDR_ADDRESS_DELIVERIES_TO_CONTAINER   11
#define QDR_ADDRESS_DELIVERIES_FROM_CONTAINER 12


static void qdr_insert_address_columns_CT(qdr_address_t        *addr,
                                          qd_composed_field_t  *body,
                                          int column_index)
{
    switch(column_index) {
        case QDR_ADDRESS_NAME:
        case QDR_ADDRESS_IDENTITY:
        case QDR_ADDRESS_KEY:
            if (addr->hash_handle)
                qd_compose_insert_string(body, (const char*) qd_hash_key_by_handle(addr->hash_handle));
            else
                qd_compose_insert_null(body);
            break;

        case QDR_ADDRESS_TYPE:
            qd_compose_insert_string(body, "org.apache.qpid.dispatch.router.address");
            break;

        case QDR_ADDRESS_IN_PROCESS:
            qd_compose_insert_uint(body, DEQ_SIZE(addr->subscriptions));
            break;

        case QDR_ADDRESS_SUBSCRIBER_COUNT:
            qd_compose_insert_uint(body, DEQ_SIZE(addr->rlinks));
            break;

        case QDR_ADDRESS_REMOTE_COUNT:
            qd_compose_insert_uint(body, qd_bitmask_cardinality(addr->rnodes));
            break;

        case QDR_ADDRESS_HOST_ROUTERS:
            qd_compose_insert_null(body);  // TEMP
            break;

        case QDR_ADDRESS_DELIVERIES_INGRESS:
            qd_compose_insert_ulong(body, addr->deliveries_ingress);
            break;

        case QDR_ADDRESS_DELIVERIES_EGRESS:
            qd_compose_insert_ulong(body, addr->deliveries_egress);
            break;

        case QDR_ADDRESS_DELIVERIES_TRANSIT:
            qd_compose_insert_ulong(body, addr->deliveries_transit);
            break;

        case QDR_ADDRESS_DELIVERIES_TO_CONTAINER:
            qd_compose_insert_ulong(body, addr->deliveries_to_container);
            break;

        case QDR_ADDRESS_DELIVERIES_FROM_CONTAINER:
            qd_compose_insert_ulong(body, addr->deliveries_from_container);
            break;

        default:
            qd_compose_insert_null(body);
            break;
    }

}

static void qdr_manage_write_address_map_CT(qdr_address_t       *addr,
                                            qd_composed_field_t *body,
                                            const char          *qdr_address_columns[])
{
    qd_compose_start_map(body);

    for(int i = 0; i < QDR_ADDRESS_COLUMN_COUNT; i++) {
        qd_compose_insert_string(body, qdr_address_columns[i]);
        qdr_insert_address_columns_CT(addr, body, i);
    }

    qd_compose_end_map(body);
}


static void qdr_manage_write_address_list_CT(qdr_query_t *query, qdr_address_t *addr)
{
    qd_composed_field_t *body = query->body;

    qd_compose_start_list(body);

    if (!addr)
        return;

    int i = 0;
    while (query->columns[i] >= 0) {
        qdr_insert_address_columns_CT(addr, body, query->columns[i]);
        i++;
    }

    qd_compose_end_list(body);
}


static void qdr_manage_advance_address_CT(qdr_query_t *query, qdr_address_t *addr)
{
    query->next_offset++;
    addr = DEQ_NEXT(addr);
    if (addr) {
        query->more     = true;
        query->next_key = qdr_field((const char*) qd_hash_key_by_handle(addr->hash_handle));
    } else
        query->more = false;
}

void qdra_address_get_CT(qdr_core_t          *core,
                         qd_field_iterator_t *name,
                         qd_field_iterator_t *identity,
                         qdr_query_t         *query,
                         const char          *qdr_address_columns[])
{
    qdr_address_t *addr;

    if (identity) //If there is identity, ignore the name
        qd_hash_retrieve(core->addr_hash, identity, (void*) &addr);
    else if (name)
        qd_hash_retrieve(core->addr_hash, name, (void*) &addr);

    if (addr == 0) {
        // Send back a 404
        query->status = &QD_AMQP_NOT_FOUND;
    }
    else {
        //
        // Write the columns of the address entity into the response body.
        //
        qdr_manage_write_address_map_CT(addr, query->body, qdr_address_columns);
        query->status = &QD_AMQP_OK;
    }

    //
    // Enqueue the response.
    //
    qdr_agent_enqueue_response_CT(core, query);

}


void qdra_address_get_first_CT(qdr_core_t *core, qdr_query_t *query, int offset)
{
    //
    // Queries that get this far will always succeed.
    //
    query->status = &QD_AMQP_OK;

    //
    // If the offset goes beyond the set of addresses, end the query now.
    //
    if (offset >= DEQ_SIZE(core->addrs)) {
        query->more = false;
        qdr_agent_enqueue_response_CT(core, query);
        return;
    }

    //
    // Run to the address at the offset.
    //
    qdr_address_t *addr = DEQ_HEAD(core->addrs);
    for (int i = 0; i < offset && addr; i++)
        addr = DEQ_NEXT(addr);
    assert(addr != 0);

    //
    // Write the columns of the address entity into the response body.
    //
    qdr_manage_write_address_list_CT(query, addr);

    //
    // Advance to the next address
    //
    query->next_offset = offset;
    qdr_manage_advance_address_CT(query, addr);

    //
    // Enqueue the response.
    //
    qdr_agent_enqueue_response_CT(core, query);
}


void qdra_address_get_next_CT(qdr_core_t *core, qdr_query_t *query)
{
    qdr_address_t *addr = 0;

    //
    // Use the stored key to try to find the next entry in the table.
    //
    if (query->next_key) {
        qd_hash_retrieve(core->addr_hash, query->next_key->iterator, (void**) &addr);
        qdr_field_free(query->next_key);
        query->next_key = 0;
    }
    if (!addr) {
        //
        // If the address was removed in the time between this get and the previous one,
        // we need to use the saved offset, which is less efficient.
        //
        if (query->next_offset < DEQ_SIZE(core->addrs)) {
            addr = DEQ_HEAD(core->addrs);
            for (int i = 0; i < query->next_offset && addr; i++)
                addr = DEQ_NEXT(addr);
        }
    }

    if (addr) {
        //
        // Write the columns of the address entity into the response body.
        //
        qdr_manage_write_address_list_CT(query, addr);

        //
        // Advance to the next address
        //
        qdr_manage_advance_address_CT(query, addr);
    } else
        query->more = false;

    //
    // Enqueue the response.
    //
    qdr_agent_enqueue_response_CT(core, query);
}

void qdra_address_delete_CT(qdr_core_t          *core,
                             qd_field_iterator_t *name,
                             qd_field_iterator_t *identity,
                             qdr_query_t          *query)
{
    bool success = true;

    if (identity) {//If there is identity, ignore the name
       //TOOD - do something here
    }
    else if (name) {
       //TOOD - do something here
    }
    else {
        query->status = &QD_AMQP_BAD_REQUEST;
        success = false;
    }


    // TODO - Add more logic here.
    if (success) {
        // If the request was successful then the statusCode MUST be 204 (No Content).
        query->status = &QD_AMQP_NO_CONTENT;
    }

    //
    // Enqueue the response.
    //
    qdr_agent_enqueue_response_CT(core, query);
}