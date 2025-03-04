{-# LANGUAGE QuasiQuotes #-}

-- | Tests for object remote relationships to databases. Remote relationships
-- are relationships that are not local to a given source or remote schema, and
-- are handled by the engine itself. Object relationsips are 1-to-1
-- relationships.
--
-- All tests use the same GraphQL syntax, and the only difference is in the
-- setup: we do a cartesian product of all kinds of sources we support on the
-- left-hand side and all databases we support on the right-hand side.
module Test.RemoteRelationship.XToDBObjectRelationshipSpec
  ( spec,
  )
where

import Data.Aeson (Value)
import Harness.Backend.Postgres qualified as Postgres
import Harness.GraphqlEngine qualified as GraphqlEngine
import Harness.Quoter.Graphql (graphql)
import Harness.Quoter.Yaml (shouldReturnYaml, yaml)
import Harness.State (Server, State)
import Harness.Test.Context (Context (..))
import Harness.Test.Context qualified as Context
import Harness.Test.Schema qualified as Schema
import Test.Hspec (SpecWith, describe, it)
import Prelude

--------------------------------------------------------------------------------
-- Preamble

spec :: SpecWith State
spec = Context.runWithLocalState contexts tests
  where
    lhsContexts = [lhsPostgres]
    rhsContexts = [rhsPostgres]
    contexts = combine <$> lhsContexts <*> rhsContexts

-- | Combines a lhs and a rhs.
--
-- The rhs is set up first, then the lhs can create the remote relationship.
--
-- Teardown is done in the opposite order.
--
-- The metadata is cleared befored each setup.
combine :: LHSContext -> RHSContext -> Context (Maybe Server)
combine lhs (tableName, rhs) =
  Context
    { name = Context.Combine lhsName rhsName,
      mkLocalState = lhsMkLocalState,
      setup = \(state, localState) -> do
        GraphqlEngine.clearMetadata state
        rhsSetup (state, ())
        lhsSetup (state, localState),
      teardown = \state@(globalState, _) -> do
        lhsTeardown state
        rhsTeardown (globalState, ()),
      customOptions =
        Context.combineOptions lhsOptions rhsOptions
    }
  where
    Context
      { name = lhsName,
        mkLocalState = lhsMkLocalState,
        setup = lhsSetup,
        teardown = lhsTeardown,
        customOptions = lhsOptions
      } = lhs tableName
    Context
      { name = rhsName,
        setup = rhsSetup,
        teardown = rhsTeardown,
        customOptions = rhsOptions
      } = rhs

--------------------------------------------------------------------------------

-- | LHS context.
--
-- Each LHS context is responsible for setting up the remote relationship, and
-- for tearing it down. Each lhs context is given the JSON representation for
-- the table name on the RHS.
type LHSContext = Value -> Context (Maybe Server)

lhsPostgres :: LHSContext
lhsPostgres tableName =
  Context
    { name = Context.Backend Context.Postgres,
      mkLocalState = lhsPostgresMkLocalState,
      setup = lhsPostgresSetup tableName,
      teardown = lhsPostgresTeardown,
      customOptions = Nothing
    }

{-
lhsRemoteServer :: Value -> Context
lhsRemoteServer tableName = Context "from RS" (lhsRemoteSetup tableName) lhsRemoteTeardown
-}

--------------------------------------------------------------------------------

-- | RHS context
--
-- Each RHS context is responsible for setting up the target table, and for
-- returning the JSON representation of said table.
type RHSContext = (Value, Context ())

rhsPostgres :: RHSContext
rhsPostgres =
  let table =
        [yaml|
      schema: hasura
      name: album
    |]
      context =
        Context
          { name = Context.Backend Context.Postgres,
            mkLocalState = Context.noLocalState,
            setup = rhsPostgresSetup,
            teardown = rhsPostgresTeardown,
            customOptions = Nothing
          }
   in (table, context)

{-
rhsMSSQL :: (Value, Context)
rhsMSSQL = ([yaml|{"schema":"hasura", "name":"album"}|], Context "MSSQL" rhsMSSQLSetup rhsMSSQLTeardown)
-}

--------------------------------------------------------------------------------
-- Schema

-- | LHS
track :: Schema.Table
track =
  Schema.Table
    "track"
    [ Schema.column "id" Schema.TInt,
      Schema.column "title" Schema.TStr,
      Schema.columnNull "album_id" Schema.TInt
    ]
    ["id"]
    []
    [ [Schema.VInt 1, Schema.VStr "track1_album1", Schema.VInt 1],
      [Schema.VInt 2, Schema.VStr "track2_album1", Schema.VInt 1],
      [Schema.VInt 3, Schema.VStr "track3_album1", Schema.VInt 1],
      [Schema.VInt 4, Schema.VStr "track1_album2", Schema.VInt 2],
      [Schema.VInt 5, Schema.VStr "track2_album2", Schema.VInt 2],
      [Schema.VInt 6, Schema.VStr "track1_album3", Schema.VInt 3],
      [Schema.VInt 7, Schema.VStr "track2_album3", Schema.VInt 3],
      [Schema.VInt 8, Schema.VStr "track_no_album", Schema.VNull]
    ]

-- | RHS
album :: Schema.Table
album =
  Schema.Table
    "album"
    [ Schema.column "id" Schema.TInt,
      Schema.column "title" Schema.TStr,
      Schema.columnNull "artist_id" Schema.TInt
    ]
    ["id"]
    []
    [ [Schema.VInt 1, Schema.VStr "album1_artist1", Schema.VInt 1],
      [Schema.VInt 2, Schema.VStr "album2_artist1", Schema.VInt 1],
      [Schema.VInt 3, Schema.VStr "album3_artist2", Schema.VInt 2]
    ]

--------------------------------------------------------------------------------
-- LHS Postgres

lhsPostgresMkLocalState :: State -> IO (Maybe Server)
lhsPostgresMkLocalState _ = pure Nothing

lhsPostgresSetup :: Value -> (State, Maybe Server) -> IO ()
lhsPostgresSetup rhsTableName (state, _) = do
  let sourceName = "source"
      sourceConfig = Postgres.defaultSourceConfiguration
      schemaName = Context.defaultSchema Context.Postgres
  -- Add remote source
  GraphqlEngine.postMetadata_
    state
    [yaml|
type: pg_add_source
args:
  name: *sourceName
  configuration: *sourceConfig
|]
  -- setup tables only
  Postgres.createTable track
  Postgres.insertTable track
  Schema.trackTable Context.Postgres sourceName track state
  GraphqlEngine.postMetadata_
    state
    [yaml|
type: bulk
args:
- type: pg_create_select_permission
  args:
    source: *sourceName
    role: role1
    table:
      schema: *schemaName
      name: track
    permission:
      columns: '*'
      filter: {}
- type: pg_create_select_permission
  args:
    source: *sourceName
    role: role2
    table:
      schema: *schemaName
      name: track
    permission:
      columns: '*'
      filter: {}
- type: pg_create_remote_relationship
  args:
    source: *sourceName
    table:
      schema: *schemaName
      name: track
    name: album
    definition:
      to_source:
        source: target
        table: *rhsTableName
        relationship_type: object
        field_mapping:
          album_id: id
  |]

lhsPostgresTeardown :: (State, Maybe Server) -> IO ()
lhsPostgresTeardown (state, _) = do
  let sourceName = "source"
  Schema.untrackTable Context.Postgres sourceName track state
  Postgres.dropTable track

--------------------------------------------------------------------------------
-- RHS Postgres

rhsPostgresSetup :: (State, ()) -> IO ()
rhsPostgresSetup (state, _) = do
  let sourceName = "target"
      sourceConfig = Postgres.defaultSourceConfiguration
      schemaName = Context.defaultSchema Context.Postgres
  -- Add remote source
  GraphqlEngine.postMetadata_
    state
    [yaml|
type: pg_add_source
args:
  name: *sourceName
  configuration: *sourceConfig
|]
  -- setup tables only
  Postgres.createTable album
  Postgres.insertTable album
  Schema.trackTable Context.Postgres sourceName album state

  GraphqlEngine.postMetadata_
    state
    [yaml|
type: bulk
args:
- type: pg_create_select_permission
  args:
    source: *sourceName
    role: role1
    table:
      schema: *schemaName
      name: album
    permission:
      columns:
        - title
        - artist_id
      filter:
        artist_id:
          _eq: x-hasura-artist-id
- type: pg_create_select_permission
  args:
    source: *sourceName
    role: role2
    table:
      schema: *schemaName
      name: album
    permission:
      columns: [id, title, artist_id]
      filter:
        artist_id:
          _eq: x-hasura-artist-id
      limit: 1
      allow_aggregations: true
  |]

rhsPostgresTeardown :: (State, ()) -> IO ()
rhsPostgresTeardown (state, _) = do
  let sourceName = "target"
  Schema.untrackTable Context.Postgres sourceName album state
  Postgres.dropTable album

--------------------------------------------------------------------------------
-- Tests

tests :: Context.Options -> SpecWith (State, Maybe Server)
tests opts = describe "object-relationship" $ do
  schemaTests opts
  executionTests opts
  permissionTests opts

-- | Basic queries using *-to-DB joins
executionTests :: Context.Options -> SpecWith (State, Maybe Server)
executionTests opts = describe "execution" $ do
  -- fetches the relationship data
  it "related-data" $ \(state, _) -> do
    let query =
          [graphql|
          query {
            track: hasura_track(where: {title: {_eq: "track1_album1"}}) {
              title
              album {
                title
              }
            }
          }
          |]
        expectedResponse =
          [yaml|
          data:
            track:
             - title: "track1_album1"
               album:
                 title: album1_artist1
          |]
    shouldReturnYaml
      opts
      (GraphqlEngine.postGraphql state query)
      expectedResponse

  -- when any of the join columns are null, the relationship should be null
  it "related-data-null" $ \(state, _) -> do
    let query =
          [graphql|
          query {
            track: hasura_track(where: {title: {_eq: "track_no_album"}}) {
              title
              album {
                title
              }
            }
          }
          |]
        expectedResponse =
          [yaml|
          data:
            track:
             - title: "track_no_album"
               album: null
          |]
    shouldReturnYaml
      opts
      (GraphqlEngine.postGraphql state query)
      expectedResponse

  -- when the lhs response has both null and non-null values for join columns
  it "related-data-non-null-and-null" $ \(state, _) -> do
    let query =
          [graphql|
          query {
            track: hasura_track(
              where: {
                _or: [
                  {title: {_eq: "track1_album1"}},
                  {title: {_eq: "track_no_album"}}
                ]
              },
              order_by: {id: asc}
            ) {
              title
              album {
                title
              }
            }
          }
          |]
        expectedResponse =
          [yaml|
          data:
            track:
             - title: "track1_album1"
               album:
                 title: album1_artist1
             - title: "track_no_album"
               album: null
          |]
    shouldReturnYaml
      opts
      (GraphqlEngine.postGraphql state query)
      expectedResponse

-- | Spec that describe an object relationship's data in the presence of
-- permisisons.
permissionTests :: Context.Options -> SpecWith (State, Maybe Server)
permissionTests opts = describe "permission" $ do
  let userHeaders = [("x-hasura-role", "role1"), ("x-hasura-artist-id", "1")]

  -- only the allowed rows on the target table are queryable
  it "only-allowed-rows" $ \(state, _) -> do
    let query =
          [graphql|
          query {
            track: hasura_track(
              order_by: {id: asc}
            ) {
              title
              album {
                title
              }
            }
          }
          |]
        expectedResponse =
          [yaml|
          data:
            track:
             - title: "track1_album1"
               album:
                 title: album1_artist1
             - title: "track2_album1"
               album:
                 title: album1_artist1
             - title: "track3_album1"
               album:
                 title: album1_artist1
             - title: "track1_album2"
               album:
                 title: album2_artist1
             - title: "track2_album2"
               album:
                 title: album2_artist1
             - title: "track1_album3"
               album: null
             - title: "track2_album3"
               album: null
             - title: "track_no_album"
               album: null
          |]
    shouldReturnYaml
      opts
      (GraphqlEngine.postGraphqlWithHeaders state userHeaders query)
      expectedResponse

  -- we use an introspection query to check column permissions:
  -- 1. the type 'hasura_album' has only 'artist_id' and 'title', the allowed columns
  -- 2. the album field in 'hasura_track' type is of type 'hasura_album'
  it "only-allowed-columns" $ \(state, _) -> do
    let query =
          [graphql|
          query {
            album_fields: __type(name: "hasura_album") {
              fields {
                name
              }
            }
            track: hasura_track(where: {title: {_eq: "track1_album1"}}) {
              title
              album {
                __typename
              }
            }
          }
          |]
        expectedResponse =
          [yaml|
          data:
            album_fields:
              fields:
              - name: artist_id
              - name: title
            track:
            - title: track1_album1
              album:
                __typename: hasura_album
          |]
    shouldReturnYaml
      opts
      (GraphqlEngine.postGraphqlWithHeaders state userHeaders query)
      expectedResponse

schemaTests :: Context.Options -> SpecWith (State, Maybe Server)
schemaTests opts =
  -- we use an introspection query to check:
  -- 1. a field 'album' is added to the track table
  -- 1. track's where clause does not have 'album' field
  -- 2. track's order_by clause does nat have 'album' field
  it "graphql-schema" $ \(state, _) -> do
    let query =
          [graphql|
          query {
            track_fields: __type(name: "hasura_track") {
              fields {
                name
              }
            }
            track_where_exp_fields: __type(name: "hasura_track_bool_exp") {
              inputFields {
                name
              }
            }
            track_order_by_exp_fields: __type(name: "hasura_track_order_by") {
              inputFields {
                name
              }
            }
          }
          |]
        expectedResponse =
          [yaml|
          data:
            track_fields:
              fields:
              - name: album
              - name: album_id
              - name: id
              - name: title
            track_where_exp_fields:
              inputFields:
              - name: _and
              - name: _not
              - name: _or
              - name: album_id
              - name: id
              - name: title
            track_order_by_exp_fields:
              inputFields:
              - name: album_id
              - name: id
              - name: title
          |]
    shouldReturnYaml
      opts
      (GraphqlEngine.postGraphql state query)
      expectedResponse
