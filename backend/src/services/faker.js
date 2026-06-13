import { faker } from '@faker-js/faker';

const FIELD_TYPES = {
  // Person
  firstName:    () => faker.person.firstName(),
  lastName:     () => faker.person.lastName(),
  fullName:     () => faker.person.fullName(),
  email:        () => faker.internet.email(),
  phone:        () => faker.phone.number(),
  avatar:       () => faker.image.avatar(),
  username:     () => faker.internet.username(),
  password:     () => faker.internet.password(),
  // Address
  street:       () => faker.location.streetAddress(),
  city:         () => faker.location.city(),
  state:        () => faker.location.state(),
  country:      () => faker.location.country(),
  zipCode:      () => faker.location.zipCode(),
  latitude:     () => faker.location.latitude(),
  longitude:    () => faker.location.longitude(),
  // Commerce
  productName:  () => faker.commerce.productName(),
  price:        () => parseFloat(faker.commerce.price()),
  department:   () => faker.commerce.department(),
  // Company
  companyName:  () => faker.company.name(),
  jobTitle:     () => faker.person.jobTitle(),
  // Date / Number / Misc
  date:         () => faker.date.past().toISOString(),
  uuid:         () => faker.string.uuid(),
  number:       () => faker.number.int({ min: 1, max: 1000 }),
  boolean:      () => faker.datatype.boolean(),
  word:         () => faker.lorem.word(),
  sentence:     () => faker.lorem.sentence(),
  paragraph:    () => faker.lorem.paragraph(),
  color:        () => faker.color.human(),
  url:          () => faker.internet.url(),
};

export const SUPPORTED_TYPES = Object.keys(FIELD_TYPES);

export function generateDocuments(schema, count = 10) {
  const docs = [];
  for (let i = 0; i < count; i++) {
    const doc = {};
    for (const [fieldName, fieldType] of Object.entries(schema)) {
      const generator = FIELD_TYPES[fieldType];
      doc[fieldName] = generator ? generator() : null;
    }
    docs.push(doc);
  }
  return docs;
}
